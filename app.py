"""
FastAPI backend for the Lead Generation Agent.
Exposes the LangGraph pipeline via SSE for real-time progress streaming.
"""

import sys
import os
import json
import queue
import threading

from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.graph import build_graph

app = FastAPI(title="LeadFlow AI")
app.mount("/static", StaticFiles(directory="static"), name="static")


class RunRequest(BaseModel):
    target_industry: str
    icp_description: str
    num_leads: int = 10
    sender_context: str = "I build AI-powered automation tools that help SaaS companies reduce manual operations"


class OutputCapture:
    """Redirects stdout into a queue, detecting pipeline stage changes."""

    def __init__(self, q):
        self.queue = q
        self.original = sys.stdout

    def write(self, text):
        stripped = text.strip()
        if not stripped:
            return
        self.original.write(text)
        self.queue.put({"type": "log", "message": stripped})

        if "[Agent] Searching" in stripped:
            self.queue.put({"type": "stage", "stage": "search"})
        elif "[Agent] Enriching" in stripped:
            self.queue.put({"type": "stage", "stage": "enrich"})
        elif "[Agent] Scoring" in stripped:
            self.queue.put({"type": "stage", "stage": "score"})
        elif "[Agent] Writing emails" in stripped:
            self.queue.put({"type": "stage", "stage": "email"})

    def flush(self):
        self.original.flush()


@app.get("/")
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.post("/api/run")
async def run_agent(request: RunRequest):
    async def event_stream():
        q = queue.Queue()

        def run():
            capture = OutputCapture(q)
            old_stdout = sys.stdout
            sys.stdout = capture
            try:
                agent = build_graph()
                initial_state = {
                    "target_industry": request.target_industry,
                    "icp_description": request.icp_description,
                    "num_leads": request.num_leads,
                    "leads": [],
                    "search_queries": [],
                    "errors": [],
                    "is_complete": False,
                    "final_summary": "",
                }
                result = agent.invoke(initial_state)

                leads = []
                for lead in result.get("leads", []):
                    leads.append({
                        "company_name": lead.get("company_name", "Unknown"),
                        "website": lead.get("website", ""),
                        "description": lead.get("description", "")[:300],
                        "score": lead.get("score", 0),
                        "score_reason": lead.get("score_reason", ""),
                        "email_draft": lead.get("email_draft", ""),
                        "linkedin_url": lead.get("linkedin_url", ""),
                    })

                q.put({
                    "type": "result",
                    "data": {
                        "leads": leads,
                        "summary": result.get("final_summary", ""),
                    }
                })
            except Exception as e:
                q.put({"type": "error", "message": str(e)})
            finally:
                sys.stdout = old_stdout
                q.put({"type": "done"})

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        while True:
            try:
                msg = q.get(timeout=1.0)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                yield ": keepalive\n\n"
                if not thread.is_alive():
                    break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
