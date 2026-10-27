"""Offline gate regression, or opt-in live-model evaluation against fixed fictional evidence."""
import argparse
import json
from pathlib import Path
import time
from agent.demo import fixture_data, case_lead, case_assessment
from agent.runtime import RunContext, current_run
from tools.scorer import apply_assessment, criterion_inputs, score_lead


def evaluate(live=False):
    data = fixture_data()
    requirements = criterion_inputs(data["industry"], data["icp"])
    rows = []
    context = RunContext()
    token = current_run.set(context)
    started = time.monotonic()
    try:
        for case in data["cases"]:
            lead = case_lead(case)
            result = (score_lead(lead, data["icp"], data["industry"]) if live else
                      apply_assessment(lead, case_assessment(case, requirements), requirements))
            rows.append({"id": case["id"], "expected": case["expected"],
                         "actual": result["qualification_status"],
                         "scoring_status": result["scoring_status"],
                         "passed": result["qualification_status"] == case["expected"]})
    finally:
        current_run.reset(token)
    tp = sum(r["actual"] == r["expected"] == "qualified" for r in rows)
    fp = sum(r["actual"] == "qualified" and r["expected"] != "qualified" for r in rows)
    fn = sum(r["actual"] != "qualified" and r["expected"] == "qualified" for r in rows)
    return {"evaluation": "live_model_synthetic_evidence" if live else "offline_policy_regression",
            "limitations": data["notice"] + " Offline mode checks supplied assessments, not model accuracy. "
                            "Exact quote validation does not prove semantic entailment or source truth.",
            "cases": rows, "accuracy": sum(r["passed"] for r in rows) / len(rows),
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "elapsed_seconds": round(time.monotonic() - started, 4), "usage": context.metrics}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Uses Groq API credits; never enabled in CI")
    parser.add_argument("--output", default="evals/latest.json")
    args = parser.parse_args()
    if args.live:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    report = evaluate(args.live)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if all(row["passed"] for row in report["cases"]) else 1)
