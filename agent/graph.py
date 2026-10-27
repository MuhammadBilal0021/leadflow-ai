"""A fixed, observable search -> enrich -> score -> draft LangGraph workflow."""
from functools import wraps
import time
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.runtime import check_run, emit, current_run
from tools.search import search_companies, extract_company_info
from tools.scraper import enrich_all_leads
from tools.scorer import score_all_leads
from tools.email_writer import write_all_emails


def stage(name):
    def decorate(fn):
        @wraps(fn)
        def run(state):
            check_run()
            emit({"type": "stage", "stage": name})
            start = time.monotonic()
            try:
                return fn(state)
            finally:
                context = current_run.get()
                if context:
                    context.metrics["stage_seconds"][name] = round(time.monotonic() - start, 3)
        return run
    return decorate


@stage("search")
def search_node(state):
    result = search_companies(state["target_industry"], state["icp_description"],
                              state.get("search_queries", []), state.get("num_leads", 10))
    if result["error"]:
        return {"leads": [], "errors": [result["error"]], "status": "failed",
                "is_complete": False, "final_summary": result["error"]}
    return {"leads": [extract_company_info(raw) for raw in result["results"]],
            "search_queries": result["queries_used"], "errors": result.get("warnings", [])}


@stage("enrich")
def enrich_node(state):
    return {"leads": enrich_all_leads(state.get("leads", []))}


@stage("score")
def score_node(state):
    return {"leads": score_all_leads(state.get("leads", []), state["icp_description"],
        state["target_industry"], state.get("qualification_criteria", []))}


@stage("email")
def email_node(state):
    leads = write_all_emails(state.get("leads", []), state["icp_description"], state["sender_context"])
    failures = sum(l.get("scoring_status") == "failed" or l.get("email_status") == "failed" for l in leads)
    errors = list(state.get("errors", []))
    if failures:
        errors.append(f"{failures} leads have unavailable scoring or drafts.")
    qualified = sum(l["qualification_status"] == "qualified" for l in leads)
    review = sum(l["qualification_status"] == "needs_review" for l in leads)
    return {"leads": leads, "is_complete": True, "status": "partial" if errors else "complete",
            "errors": errors,
            "final_summary": f"Found {len(leads)} candidates. {qualified} source-supported matches; "
                             f"{review} need review. Email drafts require human review."}


def build_graph():
    graph = StateGraph(AgentState)
    for name, fn in [("search", search_node), ("enrich", enrich_node),
                     ("score", score_node), ("email", email_node)]:
        graph.add_node(name, fn)
    graph.set_entry_point("search")
    graph.add_conditional_edges("search", lambda state: "failed" if state.get("status") == "failed" else "ok",
                               {"failed": END, "ok": "enrich"})
    graph.add_edge("enrich", "score")
    graph.add_edge("score", "email")
    graph.add_edge("email", END)
    return graph.compile()
