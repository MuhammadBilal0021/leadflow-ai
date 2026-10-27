import csv
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock

# Ensure importing the app does not create a production database during tests.
_IMPORT_TEMP = tempfile.TemporaryDirectory()
os.environ["LEADFLOW_DB"] = str(Path(_IMPORT_TEMP.name) / "import.sqlite3")
from fastapi.testclient import TestClient
from app import create_app, estimate_cost
from storage import export_csv


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APP_ACCESS_TOKEN": "test-token", "GROQ_API_KEY": "test-groq",
            "TAVILY_API_KEY": "test-tavily", "COOKIE_SECURE": "false", "MAX_LIVE_RUNS_PER_DAY": "50"})
        self.env.start()
        self.app = create_app(Path(self.temp.name) / "runs.sqlite3")
        self.client = TestClient(self.app)
        self.client.get("/api/session")
        self.input = {"target_industry": "HR tech SaaS", "icp_description": "US-based, 50-200 employees",
                      "sender_context": "I build hiring automation.", "num_leads": 6, "demo": True}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp.cleanup()

    def events(self, response):
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def run_sample(self):
        response = self.client.post("/api/run", json=self.input)
        self.assertEqual(response.status_code, 200, response.text)
        return next(event["data"] for event in self.events(response) if event["type"] == "result")

    def test_homepage_headers_and_session_cookie(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("script-src 'self'", response.headers["content-security-policy"])
        other = TestClient(self.app)
        cookie = other.get("/api/session").headers["set-cookie"]
        other.close()
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)

    def test_requires_session_and_live_token(self):
        with TestClient(self.app) as other:
            self.assertEqual(other.post("/api/run", json=self.input).status_code, 401)
        live = dict(self.input, demo=False)
        self.assertEqual(self.client.post("/api/run", json=live).status_code, 401)
        with patch.dict(os.environ, {"APP_ACCESS_TOKEN": ""}):
            self.assertEqual(self.client.post("/api/run", json=live,
                headers={"Authorization": "Bearer test-token"}).status_code, 401)

    def test_validation_and_body_limit(self):
        for update in [{"num_leads": -1}, {"num_leads": 0}, {"num_leads": 1000000},
                       {"num_leads": "10"}, {"target_industry": " "}, {"icp_description": "x" * 1501},
                       {"qualification_criteria": ["x"]}, {"unexpected": True}]:
            self.assertEqual(self.client.post("/api/run", json=dict(self.input, **update)).status_code, 422)
        response = self.client.post("/api/run", content=iter([b"x" * 9000, b"x" * 9000]))
        self.assertEqual(response.status_code, 413)

    def test_cross_origin_mutation_rejected(self):
        response = self.client.post("/api/run", json=self.input, headers={"Origin": "https://attacker.example"})
        self.assertEqual(response.status_code, 403)

    def test_sample_save_export_and_owner_isolation(self):
        data = self.run_sample()
        run_id = data["run_id"]
        self.assertEqual(data["metrics"]["estimated_cost_usd"], 0)
        self.assertEqual(data["metrics"]["llm_requests"], 0)
        self.assertEqual(len(self.client.get("/api/runs").json()), 1)
        self.assertEqual(self.client.get("/api/runs/" + run_id).json()["run_id"], run_id)
        export = self.client.get("/api/runs/" + run_id + "/export")
        self.assertEqual(export.status_code, 200)
        self.assertEqual(len(list(csv.reader(io.StringIO(export.text)))), 7)
        with TestClient(self.app) as other:
            other.get("/api/session")
            self.assertEqual(other.get("/api/runs").json(), [])
            for suffix in ["", "/export"]:
                self.assertEqual(other.get("/api/runs/" + run_id + suffix).status_code, 404)
            self.assertEqual(other.delete("/api/runs/" + run_id).status_code, 404)
        self.assertTrue(self.client.delete("/api/runs/" + run_id).json()["deleted"])
        self.assertEqual(self.client.get("/api/runs/" + run_id).status_code, 404)

    def test_quota_and_parallel_limit(self):
        self.app.state.slots.acquire()
        self.app.state.slots.acquire()
        try:
            self.assertEqual(self.client.post("/api/run", json=self.input).status_code, 429)
        finally:
            self.app.state.slots.release()
            self.app.state.slots.release()
        store = self.app.state.store
        owner = store.session(self.client.cookies.get("leadflow_session"))
        for _ in range(10):
            store.admit(owner, "a-test-ip", False, 50)
        self.assertEqual(self.client.post("/api/run", json=self.input).status_code, 429)

    def test_slow_run_does_not_block_other_requests(self):
        started, release = threading.Event(), threading.Event()
        def invoke(state):
            started.set()
            release.wait(3)
            return {"leads": [], "status": "complete", "final_summary": "Mock"}
        graph = MagicMock()
        graph.invoke.side_effect = invoke
        with patch("agent.graph.build_graph", return_value=graph), ThreadPoolExecutor(max_workers=1) as executor, \
             TestClient(self.app) as shared:
            shared.get("/api/session")
            future = executor.submit(shared.post, "/api/run", json=dict(self.input, demo=False),
                                     headers={"Authorization": "Bearer test-token"})
            try:
                self.assertTrue(started.wait(2))
                before = time.monotonic()
                self.assertEqual(shared.get("/").status_code, 200)
                self.assertLess(time.monotonic() - before, 1)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5).status_code, 200)

    def test_disconnect_cancels_worker_without_saving(self):
        import asyncio
        from types import SimpleNamespace
        from agent.runtime import check_run, current_run
        owner = self.app.state.store.session(self.client.cookies.get("leadflow_session"))
        endpoint = next(route.endpoint for route in self.app.routes if getattr(route, "path", None) == "/api/run")
        stopped = threading.Event()
        graph = MagicMock()
        def invoke(state):
            try:
                current_run.get().cancelled.wait(2)
                check_run()
                return {"leads": []}
            finally:
                stopped.set()
        graph.invoke.side_effect = invoke
        async def disconnected():
            return True
        async def consume():
            from app import RunRequest
            request = SimpleNamespace(headers={"authorization": "Bearer test-token"},
                client=SimpleNamespace(host="testclient"), is_disconnected=disconnected)
            response = await endpoint(RunRequest(**dict(self.input, demo=False)), request, owner)
            async for chunk in response.body_iterator:
                pass
        with patch("agent.graph.build_graph", return_value=graph):
            asyncio.run(consume())
            self.assertTrue(stopped.wait(2))
        self.assertEqual(self.app.state.store.list(owner), [])

    def test_provider_exception_does_not_leak_secrets(self):
        with patch("agent.graph.build_graph", side_effect=RuntimeError("TOP_SECRET_PROVIDER_TOKEN")):
            response = self.client.post("/api/run", json=dict(self.input, demo=False),
                                       headers={"Authorization": "Bearer test-token"})
        self.assertNotIn("TOP_SECRET", response.text)
        self.assertEqual([event["type"] for event in self.events(response)], ["error", "done"])

    def test_failed_search_status_is_saved(self):
        graph = MagicMock()
        graph.invoke.return_value = {"status": "failed", "is_complete": False, "leads": [],
                                     "errors": ["Search unavailable"], "final_summary": "Search unavailable"}
        with patch("agent.graph.build_graph", return_value=graph):
            response = self.client.post("/api/run", json=dict(self.input, demo=False),
                                       headers={"Authorization": "Bearer test-token"})
        data = next(event["data"] for event in self.events(response) if event["type"] == "result")
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["warnings"], ["Search unavailable"])


class ExportTests(unittest.TestCase):
    def test_csv_formula_injection_escaped(self):
        for value in ["=HYPERLINK(1)", "+cmd", "-cmd", "@SUM(1)", "  =1+1", "\t=1+1"]:
            output = export_csv({"leads": [{"company_name": value}]})
            row = list(csv.reader(io.StringIO(output)))[1]
            self.assertTrue(row[0].startswith("'"))

    def test_cost_not_invented(self):
        metrics = {"input_tokens": 1000000, "output_tokens": 1000000, "search_credits": 2}
        with patch.dict(os.environ, {"GROQ_INPUT_USD_PER_MILLION": "", "GROQ_OUTPUT_USD_PER_MILLION": "",
                                    "TAVILY_USD_PER_CREDIT": ""}):
            self.assertIsNone(estimate_cost(metrics, False))
        with patch.dict(os.environ, {"GROQ_INPUT_USD_PER_MILLION": "1", "GROQ_OUTPUT_USD_PER_MILLION": "2",
                                    "TAVILY_USD_PER_CREDIT": "0.1"}):
            self.assertEqual(estimate_cost(metrics, False), 3.2)
