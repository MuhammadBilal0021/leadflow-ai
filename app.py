"""Session-owned saved runs and bounded SSE execution, with a safe offline default."""
import asyncio
from datetime import datetime, timezone
import hmac
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.runtime import RunContext, RunStopped, current_run
from storage import Store, CapacityError, digest, export_csv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
logger = logging.getLogger("leadflow")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_industry: str = Field(min_length=2, max_length=200)
    icp_description: str = Field(min_length=5, max_length=1500)
    num_leads: int = Field(default=10, ge=1, le=20, strict=True)
    sender_context: str = Field(default="I build AI-powered automation tools that reduce manual operations.",
                                min_length=5, max_length=1500)
    qualification_criteria: list[str] = Field(default_factory=list, max_length=8)
    demo: bool = True

    @field_validator("qualification_criteria")
    @classmethod
    def validate_criteria(cls, values):
        if any(not 2 <= len(value.strip()) <= 250 for value in values):
            raise ValueError("Each criterion must contain 2-250 characters")
        return list(dict.fromkeys(value.strip() for value in values))


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 16384:
                    await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            delivered = False
            original_receive = receive

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()
            await self.app(scope, replay, send)
        else:
            await self.app(scope, receive, send)


def estimate_cost(metrics, demo):
    if demo:
        return 0.0
    names = ["GROQ_INPUT_USD_PER_MILLION", "GROQ_OUTPUT_USD_PER_MILLION", "TAVILY_USD_PER_CREDIT"]
    if not all(os.getenv(name) for name in names):
        return None
    try:
        rates = [float(os.environ[name]) for name in names]
        if any(not 0 <= rate < 100000 for rate in rates):
            return None
        return round(metrics["input_tokens"] * rates[0] / 1e6 +
                     metrics["output_tokens"] * rates[1] / 1e6 +
                     metrics["search_credits"] * rates[2], 6)
    except ValueError:
        return None


def create_app(db_path=None):
    application = FastAPI(title="LeadFlow AI", version="2.0.0")
    application.add_middleware(BodyLimit)
    application.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    store = Store(db_path or os.getenv("LEADFLOW_DB", str(ROOT / "data" / "runs.sqlite3")))
    application.state.store = store
    application.state.slots = threading.BoundedSemaphore(2)

    @application.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(CapacityError)
    async def capacity_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=429, headers={"Retry-After": "3600"})

    def owner(request: Request):
        value = store.session(request.cookies.get("leadflow_session"))
        if not value:
            raise HTTPException(401, "Session expired. Refresh the page.")
        return value

    def safe_mutation(request: Request):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(403, "Cross-origin requests are not allowed.")

    @application.get("/")
    async def root():
        return HTMLResponse((ROOT / "static" / "index.html").read_text(encoding="utf-8"))

    @application.get("/api/session")
    def session(request: Request, response: Response):
        if not store.session(request.cookies.get("leadflow_session")):
            token = store.new_session()
            response.set_cookie("leadflow_session", token, httponly=True, samesite="strict",
                                secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                                max_age=7 * 86400, path="/")
        return {"live_available": all(os.getenv(key) for key in
                ["APP_ACCESS_TOKEN", "GROQ_API_KEY", "TAVILY_API_KEY"]),
                "demo_notice": "Sample companies are fictional. No APIs or live research are used."}

    @application.get("/api/runs")
    def list_runs(identity=Depends(owner)):
        return store.list(identity)

    def get_run(identity, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise HTTPException(404, "Run not found")
        payload = store.get(identity, run_id)
        if payload is None:
            raise HTTPException(404, "Run not found")
        return payload

    @application.get("/api/runs/{run_id}")
    def read_run(run_id: str, identity=Depends(owner)):
        return get_run(identity, run_id)

    @application.get("/api/runs/{run_id}/export")
    def download(run_id: str, identity=Depends(owner)):
        return Response(export_csv(get_run(identity, run_id)), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="leadflow-{run_id}.csv"'})

    @application.delete("/api/runs/{run_id}", dependencies=[Depends(safe_mutation)])
    def delete_run(run_id: str, identity=Depends(owner)):
        get_run(identity, run_id)
        store.delete(identity, run_id)
        return {"deleted": True}

    @application.post("/api/run", dependencies=[Depends(safe_mutation)])
    async def run_agent(payload: RunRequest, request: Request, identity=Depends(owner)):
        if not payload.demo:
            configured = os.getenv("APP_ACCESS_TOKEN", "")
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not configured or not hmac.compare_digest(supplied.encode(), configured.encode()):
                raise HTTPException(401, "A valid live access token is required.")
            if not os.getenv("GROQ_API_KEY") or not os.getenv("TAVILY_API_KEY"):
                raise HTTPException(503, "Live providers are not configured.")
        if not application.state.slots.acquire(blocking=False):
            raise HTTPException(429, "Two runs are already active. Try again shortly.")
        try:
            # Never trust X-Forwarded-For from arbitrary callers.
            ip = digest(request.client.host if request.client else "unknown")
            await asyncio.to_thread(store.admit, identity, ip, not payload.demo,
                                    int(os.getenv("MAX_LIVE_RUNS_PER_DAY", "50")))
        except BaseException:
            application.state.slots.release()
            raise
        loop = asyncio.get_running_loop()
        events = asyncio.Queue(maxsize=128)
        disconnected = threading.Event()
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        created = datetime.now(timezone.utc).isoformat()

        def enqueue(event):
            if not disconnected.is_set():
                try:
                    events.put_nowait(event)
                except asyncio.QueueFull:
                    context.cancelled.set()

        def emit(event):
            try:
                loop.call_soon_threadsafe(enqueue, event)
            except RuntimeError:
                context.cancelled.set()

        context = RunContext(emit=emit, deadline=started + 240)

        def worker():
            token = current_run.set(context)
            try:
                if payload.demo:
                    from agent.demo import run_demo
                    result = run_demo(payload.model_dump())
                else:
                    from agent.graph import build_graph
                    result = build_graph().invoke(dict(payload.model_dump(exclude={"demo"}),
                        leads=[], search_queries=[], errors=[], is_complete=False, final_summary=""))
                context.check()
                metrics = context.metrics
                metrics["elapsed_seconds"] = round(time.monotonic() - started, 3)
                metrics["estimated_cost_usd"] = estimate_cost(metrics, payload.demo)
                qualified = sum(l.get("qualification_status") == "qualified" for l in result.get("leads", []))
                metrics["estimated_cost_per_qualified_lead_usd"] = (
                    round(metrics["estimated_cost_usd"] / qualified, 6)
                    if qualified and metrics["estimated_cost_usd"] is not None else None)
                metrics["cost_note"] = "Configured-rate estimate; failed requests or unreported provider usage may be excluded."
                output = {"run_id": run_id, "created_at": created, "mode": "sample" if payload.demo else "live",
                    "status": result.get("status", "failed"), "leads": result.get("leads", []),
                    "summary": result.get("final_summary", ""), "warnings": result.get("errors", []),
                    "metrics": metrics, "input": payload.model_dump()}
                store.save(identity, output)
                emit({"type": "result", "data": output})
            except RunStopped:
                emit({"type": "error", "message": "Run cancelled or time limit reached; unfinished results were not saved."})
            except Exception:
                # Do not echo provider exceptions or secrets into the client stream/logs.
                logger.warning("Run %s failed", run_id)
                emit({"type": "error", "message": "Run failed. Check provider configuration or try again."})
            finally:
                current_run.reset(token)
                emit({"type": "done"})
                application.state.slots.release()

        async def event_stream():
            thread = threading.Thread(target=worker, name=f"leadflow-{run_id}", daemon=True)
            try:
                thread.start()
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(events.get(), timeout=1)
                    except asyncio.TimeoutError:
                        if time.monotonic() >= context.deadline:
                            yield 'data: {"type":"error","message":"Run time limit reached."}\n\n'
                            break
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event["type"] == "done":
                        break
            finally:
                disconnected.set()
                context.cancelled.set()
                if not thread.ident:
                    application.state.slots.release()

        return StreamingResponse(event_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000)
