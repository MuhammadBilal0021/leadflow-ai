# agent/graph.py
# -----------------------------------------------------------------
# LangGraph pipeline: search -> enrich -> score -> email
# The enrich step fetches real company homepage content so the
# scorer has actual data to work with, not just search snippets.
# -----------------------------------------------------------------

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import StateGraph, END
from agent.state import AgentState
from tools.search import search_companies, extract_company_info
from tools.scraper import enrich_all_leads
from tools.scorer import score_all_leads
from tools.email_writer import write_all_emails

# Score threshold for "qualified" — set to 40 during testing
QUALIFIED_THRESHOLD = 40


def dedup_leads(leads: list) -> list:
    """
    Removes duplicate leads by website URL.
    Runs before scoring so we don't waste API calls on duplicates.
    """
    seen = set()
    unique = []
    for lead in leads:
        url = lead.get("website", "")
        if url not in seen:
            seen.add(url)
            unique.append(lead)
    return unique


def search_node(state: AgentState) -> dict:
    print("\n[Agent] Searching for companies...")

    result = search_companies(
        target_industry=state["target_industry"],
        icp_description=state["icp_description"],
        already_searched=state.get("search_queries", []),
        num_results=state.get("num_leads", 10),
    )

    if result["error"]:
        print(f"[Agent] Search warning: {result['error']}")
        return {
            "leads": [],
            "search_queries": state.get("search_queries", []) + result.get("queries_used", []),
            "errors": state.get("errors", []) + [result["error"]],
        }

    raw_leads = [extract_company_info(r) for r in result["results"]]
    print(f"[Agent] Found {len(raw_leads)} companies")

    return {
        "leads": raw_leads,
        "search_queries": state.get("search_queries", []) + result.get("queries_used", []),
        "errors": state.get("errors", []),
    }


def enrich_node(state: AgentState) -> dict:
    """Scrapes company websites to get richer descriptions before scoring."""
    print("\n[Agent] Enriching lead descriptions from company websites...")

    leads = state.get("leads", [])
    if not leads:
        print("[Agent] No leads to enrich -- skipping")
        return {"leads": []}

    enriched = enrich_all_leads(leads)
    print(f"[Agent] Enriched {len(enriched)} leads")

    return {"leads": enriched}


def score_node(state: AgentState) -> dict:
    print("\n[Agent] Scoring leads...")

    leads = state.get("leads", [])

    if not leads:
        print("[Agent] No leads to score -- skipping")
        return {"leads": []}

    # Deduplicate before scoring -- fixes the repeated leads issue
    unique_leads = dedup_leads(leads)
    print(f"[Agent] Deduped: {len(leads)} -> {len(unique_leads)} unique leads")

    scored_leads = score_all_leads(unique_leads, state["icp_description"])
    high_quality = [l for l in scored_leads if l["score"] >= QUALIFIED_THRESHOLD]
    print(f"[Agent] {len(high_quality)}/{len(scored_leads)} leads scored {QUALIFIED_THRESHOLD}+")

    return {"leads": scored_leads}


def email_node(state: AgentState) -> dict:
    print("\n[Agent] Writing emails...")

    leads = state.get("leads", [])

    # Deduplicate again as a safety net
    leads = dedup_leads(leads)

    sender_context = "I build AI-powered automation tools that help SaaS companies reduce manual operations"

    leads_with_emails = write_all_emails(
        leads=leads,
        icp_description=state["icp_description"],
        sender_context=sender_context,
    )

    total = len(leads_with_emails)
    qualified = len([l for l in leads_with_emails if l["score"] >= QUALIFIED_THRESHOLD])
    avg_score = sum(l["score"] for l in leads_with_emails) / total if total > 0 else 0

    summary = (
        f"Found {total} companies. "
        f"{qualified} qualified leads (score {QUALIFIED_THRESHOLD}+). "
        f"Average score: {avg_score:.0f}/100."
    )

    print(f"\n[Agent] Done. {summary}")

    return {
        "leads": leads_with_emails,
        "is_complete": True,
        "final_summary": summary,
    }


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("search", search_node)
    graph.add_node("enrich", enrich_node)
    graph.add_node("score", score_node)
    graph.add_node("email", email_node)

    graph.set_entry_point("search")
    graph.add_edge("search", "enrich")
    graph.add_edge("enrich", "score")
    graph.add_edge("score", "email")
    graph.add_edge("email", END)

    return graph.compile()


if __name__ == "__main__":
    print("Testing full agent graph...\n")

    agent = build_graph()

    initial_state = {
        "target_industry": "HR tech SaaS",
        "icp_description": "US-based, 50-200 employees, Series A or B funded",
        "num_leads": 10,
        "leads": [],
        "search_queries": [],
        "errors": [],
        "is_complete": False,
        "final_summary": "",
    }

    result = agent.invoke(initial_state)

    print("\n" + "="*50)
    print("FINAL RESULTS")
    print("="*50)
    print(f"\n{result['final_summary']}\n")

    for lead in result["leads"]:
        print(f"Company : {lead['company_name']}")
        print(f"URL     : {lead['website']}")
        print(f"Score   : {lead['score']}/100 -- {lead['score_reason']}")
        if lead['score'] >= QUALIFIED_THRESHOLD:
            print(f"Email   :\n{lead['email_draft']}")
        print("-" * 40)