import unittest
from unittest.mock import patch, MagicMock
from agent.graph import build_graph
from tools.search import search_companies, extract_company_info
from agent.demo import run_demo, fixture_data
from evals.evaluate import evaluate


class WorkflowTests(unittest.TestCase):
    def initial(self):
        return dict(target_industry="HR tech SaaS", icp_description="US-based",
                    sender_context="MY OFFER", qualification_criteria=[], num_leads=3,
                    leads=[], errors=[], search_queries=[], is_complete=False, final_summary="")

    def test_search_failure_stops_workflow(self):
        with patch("agent.graph.search_companies", return_value={"error": "Search unavailable"}), \
             patch("agent.graph.enrich_all_leads") as enrich, patch("agent.graph.write_all_emails") as emails:
            result = build_graph().invoke(self.initial())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["is_complete"])
        enrich.assert_not_called()
        emails.assert_not_called()

    def test_sorted_order_and_pitch_survive_graph(self):
        raw = [{"url": "https://a.example", "title": "A", "content": "a"},
               {"url": "https://b.example", "title": "B", "content": "b"}]
        def scored(leads, *args):
            return [dict(leads[1], score=90, scoring_status="complete", qualification_status="qualified"),
                    dict(leads[0], score=50, scoring_status="complete", qualification_status="needs_review")]
        with patch("agent.graph.search_companies", return_value={"results": raw, "error": None, "queries_used": []}), \
             patch("agent.graph.enrich_all_leads", side_effect=lambda leads: leads), \
             patch("agent.graph.score_all_leads", side_effect=scored), \
             patch("agent.graph.write_all_emails", side_effect=lambda leads,*args:leads) as emails:
            result = build_graph().invoke(self.initial())
        self.assertEqual([lead["score"] for lead in result["leads"]], [90, 50])
        self.assertEqual(emails.call_args.args[2], "MY OFFER")
        self.assertEqual(result["status"], "complete")

    def test_partial_scoring_failure_exposed(self):
        raw = [{"url": "https://a.example", "title": "A", "content": "a"}]
        with patch("agent.graph.search_companies", return_value={"results": raw, "error": None, "queries_used": []}), \
             patch("agent.graph.enrich_all_leads", side_effect=lambda leads: leads), \
             patch("agent.graph.score_all_leads", side_effect=lambda leads,*args:[dict(leads[0],scoring_status="failed")]), \
             patch("agent.graph.write_all_emails", side_effect=lambda leads,*args:leads):
            result = build_graph().invoke(self.initial())
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["errors"])

    def test_profiles_distinct_and_not_guessed_websites(self):
        raw = [{"url": "https://crunchbase.com/organization/" + name,
                "title": name, "content": "A company"} for name in ["alpha", "beta"]]
        client = MagicMock()
        client.search.return_value = {"results": raw}
        with patch.dict("os.environ", {"TAVILY_API_KEY": "placeholder"}), \
             patch("tools.search.TavilyClient", return_value=client):
            result = search_companies("HR", "US-based", [], 10)
        self.assertEqual(len(result["results"]), 2)
        lead = extract_company_info(result["results"][0])
        self.assertEqual(lead["website"], "")
        self.assertIn("/organization/", lead["profile_url"])

    def test_demo_never_calls_providers(self):
        with patch("tools.llm.Groq", side_effect=AssertionError("network")), \
             patch("tools.search.TavilyClient", side_effect=AssertionError("network")):
            result = run_demo(dict(self.initial(), num_leads=6))
        self.assertEqual(len(result["leads"]), 6)
        self.assertEqual(sum(l["qualification_status"] == "qualified" for l in result["leads"]), 2)
        self.assertTrue(all("MY OFFER" in l["email_draft"] for l in result["leads"] if l["email_draft"]))

    def test_offline_evaluation_is_labelled_as_policy_regression(self):
        report = evaluate()
        self.assertEqual(len(report["cases"]), 6)
        self.assertTrue(all(row["passed"] for row in report["cases"]))
        self.assertEqual(report["evaluation"], "offline_policy_regression")
        self.assertIn("not model accuracy", report["limitations"])
