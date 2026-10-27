"""Measure the real streaming endpoint with a mocked provider, never a paid API."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch, MagicMock


def benchmark():
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
        "LEADFLOW_DB": str(Path(directory) / "import.sqlite3"), "APP_ACCESS_TOKEN": "offline-benchmark-only",
        "GROQ_API_KEY": "unused-placeholder", "TAVILY_API_KEY": "unused-placeholder",
    }):
        from app import create_app, RunRequest
        from agent.graph import build_graph  # Preload imports outside the timed section.
        application = create_app(Path(directory) / "benchmark.sqlite3")
        store = application.state.store
        owner = store.session(store.new_session())
        endpoint = next(route.endpoint for route in application.routes if getattr(route, "path", "") == "/api/run")
        async def connected():
            return False
        request = SimpleNamespace(headers={"authorization": "Bearer offline-benchmark-only"},
            client=SimpleNamespace(host="benchmark"), is_disconnected=connected)
        graph = MagicMock()
        def invoke(state):
            time.sleep(.2)
            return {"leads": [], "status": "complete", "final_summary": "Mocked 200 ms workflow"}
        graph.invoke.side_effect = invoke
        async def measure():
            response = await endpoint(RunRequest(target_industry="HR SaaS", icp_description="US-based",
                                                  demo=False), request, owner)
            start = time.monotonic()
            async def heartbeat():
                await asyncio.sleep(.01)
                return time.monotonic() - start
            heart = asyncio.create_task(heartbeat())
            frames = []
            async for frame in response.body_iterator:
                if frame.startswith("data: "):
                    frames.append(json.loads(frame[6:]))
            delay = await heart
            result = next(event["data"] for event in frames if event["type"] == "result")
            return {"measurement": "offline_sse_with_mocked_200ms_provider",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.monotonic() - start, 4),
                "ten_ms_heartbeat_actual_seconds": round(delay, 4),
                "stream_event_types": [event["type"] for event in frames],
                "provider_calls": result["metrics"]["llm_requests"] + result["metrics"]["search_requests"],
                "limitations": "Measures streaming responsiveness with mocked work, not live provider speed or accuracy."}
        with patch("agent.graph.build_graph", return_value=graph):
            return asyncio.run(measure())


if __name__ == "__main__":
    report = benchmark()
    path = Path(__file__).resolve().parents[1] / "docs" / "benchmark.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
