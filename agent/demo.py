"""Deterministic fictional walkthrough, with no provider calls or guessed websites."""
import json
from pathlib import Path
import time
from agent.runtime import check_run, emit, current_run
from tools.scorer import Assessment, apply_assessment, criterion_inputs


def fixture_data():
    return json.loads((Path(__file__).resolve().parents[1] / "evals" / "fixtures.json").read_text(encoding="utf-8"))


def case_lead(case):
    return {"id": case["id"], "company_name": case["name"], "website": "",
        "profile_url": "", "linkedin_url": "", "description": case["text"], "email_draft": "",
        "sources": [{"id": "s0", "url": "https://example.com/fictional/" + case["id"],
                     "text": case["text"], "kind": "fictional_fixture", "retrieved_at": "2026-10-27T00:00:00+00:00"}]}


def case_assessment(case, requirements):
    citation = {"source_id": "s0", "quote": case["text"]}
    return Assessment.model_validate({"score": case["score"],
        "reason": "Fictional sample: qualification follows the supplied evidence and requirements.",
        "criteria": [{"id": requirement["id"], "verdict": case["verdicts"][i] if i < 2 else "unknown",
                      "citations": [citation] if i < 2 and case["verdicts"][i] != "unknown" else []}
                     for i, requirement in enumerate(requirements)],
        "facts": [{"field": key, "value": value, "citation": citation} for key, value in case.get("facts", {}).items()]})


def run_demo(inputs):
    data = fixture_data()
    requirements = criterion_inputs(data["industry"], data["icp"])
    leads = []
    for name in ["search", "enrich", "score", "email"]:
        check_run()
        emit({"type": "stage", "stage": name})
        start = time.monotonic()
        if name == "score":
            for case in data["cases"][:inputs["num_leads"]]:
                leads.append(apply_assessment(case_lead(case), case_assessment(case, requirements), requirements))
        if name == "email":
            for lead in leads:
                if lead["qualification_status"] == "qualified":
                    lead["email_draft"] = (
                        f"Subject: An idea for {lead['company_name']}\n\n"
                        f"Your work in HR tech caught my attention. {inputs['sender_context']} "
                        "Would you be open to a short conversation?")
                    lead["email_status"] = "draft_needs_review"
                else:
                    lead["email_status"] = "skipped"
        context = current_run.get()
        if context:
            context.metrics["stage_seconds"][name] = round(time.monotonic() - start, 3)
    leads.sort(key=lambda lead: lead["score"], reverse=True)
    return {"leads": leads, "is_complete": True, "status": "complete",
            "errors": [data["notice"]],
            "final_summary": f"Fictional walkthrough: {len(leads)} candidates for {data['industry']}; {data['icp']}. "
                             "Sample targeting is fixed; switch to live mode for your own search."}
