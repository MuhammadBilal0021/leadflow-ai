import socket
import unittest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError
from tools.urls import clean_url, company_key, profile_kind
from tools.scraper import public_addresses, fetch_html, MAX_BYTES
from tools.scorer import Assessment, apply_assessment, criterion_inputs, score_lead
from tools.email_writer import write_email
from agent.demo import fixture_data, case_lead, case_assessment
from agent.runtime import RunContext, current_run, RunStopped


class URLTests(unittest.TestCase):
    def test_unsafe_urls_rejected(self):
        for url in ["javascript:alert(1)", "file:///etc/passwd", "http://127.0.0.1/",
                    "http://169.254.169.254/", "http://[::1]/", "http://localhost/",
                    "https://user:pass@example.com/", 'https://example.com/" onmouseover="x',
                    "https://example.com:8443/", "https://example.com/\n", "https://example.com\\@evil.com/"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                clean_url(url)

    def test_profile_identity_and_host_boundaries(self):
        self.assertNotEqual(company_key("https://www.crunchbase.com/organization/a"),
                            company_key("https://www.crunchbase.com/organization/b"))
        self.assertEqual(company_key("https://www.acme.com/about"), company_key("https://acme.com/pricing"))
        self.assertIsNone(profile_kind("https://crunchbase.com.attacker.com/organization/a"))

    def test_mixed_dns_and_mapped_ipv6_rejected(self):
        for addresses in [["93.184.216.34", "10.0.0.1"], ["::ffff:127.0.0.1"], ["169.254.169.254"],
                          ["fec0::1"], ["64:ff9b::7f00:1"], ["2002:7f00:1::"]]:
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in addresses]
            with patch("tools.scraper.socket.getaddrinfo", return_value=answers), self.assertRaises(ValueError):
                public_addresses("example.com", 80)

    def response(self, status=200, headers=None, chunks=None):
        result = MagicMock()
        result.status = status
        result.headers = headers or {"Content-Type": "text/html"}
        result.connection = None
        result.read1.side_effect = chunks or [b"<html>safe</html>", b""]
        return result

    def test_tls_pins_ip_and_preserves_hostname(self):
        pool = MagicMock()
        response = self.response()
        pool.urlopen.return_value = response
        with patch("tools.scraper.public_addresses", return_value=["93.184.216.34"]), \
             patch("tools.scraper.urllib3.HTTPSConnectionPool", return_value=pool) as factory:
            text, url = fetch_html("https://example.com/about")
        self.assertIn("safe", text)
        self.assertEqual(factory.call_args.kwargs["host"], "93.184.216.34")
        self.assertEqual(factory.call_args.kwargs["server_hostname"], "example.com")
        self.assertEqual(factory.call_args.kwargs["assert_hostname"], "example.com")
        self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
        self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["Host"], "example.com")
        response.close.assert_called_once()

    def test_redirect_to_loopback_blocked(self):
        pool = MagicMock()
        pool.urlopen.return_value = self.response(302, {"Location": "http://127.0.0.1/private"})
        with patch("tools.scraper.public_addresses", return_value=["93.184.216.34"]), \
             patch("tools.scraper.urllib3.HTTPSConnectionPool", return_value=pool), self.assertRaises(ValueError):
            fetch_html("https://example.com")
        pool.urlopen.assert_called_once()

    def test_large_or_compressed_response_rejected(self):
        for headers, chunks in [
            ({"Content-Type": "text/html", "Content-Length": str(MAX_BYTES + 1)}, None),
            ({"Content-Type": "text/html", "Content-Encoding": "gzip"}, None),
            ({"Content-Type": "text/html"}, [b"x" * (MAX_BYTES + 1)]),
        ]:
            pool = MagicMock()
            pool.urlopen.return_value = self.response(headers=headers, chunks=chunks)
            with patch("tools.scraper.public_addresses", return_value=["93.184.216.34"]), \
                 patch("tools.scraper.urllib3.HTTPSConnectionPool", return_value=pool), self.assertRaises(ValueError):
                fetch_html("https://example.com")

    def test_profile_not_scraped_as_company_homepage(self):
        from tools.scraper import enrich_lead
        with patch("tools.scraper.fetch_html") as fetch:
            result = enrich_lead({"website": "", "profile_url": "https://crunchbase.com/organization/acme"})
        fetch.assert_not_called()
        self.assertEqual(result["enrichment_status"], "profile_only")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        data = fixture_data()
        self.case = data["cases"][0]
        self.lead = case_lead(self.case)
        self.requirements = criterion_inputs(data["industry"], data["icp"])

    def test_scores_are_strict_and_bounded(self):
        raw = case_assessment(self.case, self.requirements).model_dump()
        for score in [999, -1, "90", 90.1, True]:
            with self.subTest(score=score), self.assertRaises(ValidationError):
                Assessment.model_validate(dict(raw, score=score))

    def test_malformed_model_output_fails_closed(self):
        with patch("tools.scorer.complete_json", side_effect=ValueError("secret-provider-error")):
            result = score_lead(self.lead, "ICP", "HR")
        self.assertIsNone(result["score"])
        self.assertEqual(result["qualification_status"], "needs_review")
        self.assertNotIn("secret", result["score_reason"])
        with patch("tools.email_writer.complete_json") as llm:
            self.assertEqual(write_email(result, "ICP", "my pitch")["email_status"], "skipped")
            llm.assert_not_called()

    def test_invented_quote_cannot_qualify(self):
        raw = case_assessment(self.case, self.requirements).model_dump()
        for criterion in raw["criteria"]:
            criterion["citations"][0]["quote"] = "Invented supporting evidence which is absent."
        result = apply_assessment(self.lead, Assessment.model_validate(raw), self.requirements)
        self.assertEqual(result["qualification_status"], "needs_review")
        self.assertLess(result["score"], 60)

    def test_incomplete_or_duplicate_criteria_rejected(self):
        raw = case_assessment(self.case, self.requirements).model_dump()
        for criteria in [raw["criteria"][:1], [raw["criteria"][0]] * 2]:
            with self.assertRaises(ValueError):
                apply_assessment(self.lead, Assessment.model_validate(dict(raw, criteria=criteria)), self.requirements)

    def test_facts_require_literal_value_and_source(self):
        raw = case_assessment(self.case, self.requirements).model_dump()
        raw["facts"][0]["value"] = "Invented industry"
        result = apply_assessment(self.lead, Assessment.model_validate(raw), self.requirements)
        self.assertEqual(result["facts"]["industry"]["status"], "unknown")

    def test_cancelled_run_stops_scoring(self):
        context = RunContext()
        context.cancelled.set()
        token = current_run.set(context)
        try:
            with self.assertRaises(RunStopped):
                score_lead(self.lead, "ICP")
        finally:
            current_run.reset(token)

    def test_email_uses_supplied_pitch_and_evidence(self):
        from tools.email_writer import EmailDraft
        scored = apply_assessment(self.lead, case_assessment(self.case, self.requirements), self.requirements)
        with patch("tools.email_writer.complete_json", return_value=EmailDraft(subject="A subject", body="A body")) as llm:
            result = write_email(scored, "ICP", "MY ACTUAL OFFER")
        self.assertEqual(llm.call_args.args[1]["sender_offer"], "MY ACTUAL OFFER")
        self.assertEqual(result["email_status"], "draft_needs_review")
