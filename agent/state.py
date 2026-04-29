# agent/state.py
# ─────────────────────────────────────────────────────────────
# This file defines the "brain" of the agent — the shared state
# that flows through every node in the LangGraph graph.
# Think of it like a whiteboard every tool can read and write to.
# ─────────────────────────────────────────────────────────────

from typing import TypedDict, Annotated, List
import operator


class Lead(TypedDict):
    """
    Represents a single discovered lead (one company).
    Every tool reads and writes leads in this exact shape.
    """
    company_name: str        # e.g. "Acme Corp"
    website: str             # e.g. "https://acme.com"
    description: str         # scraped summary of what they do
    score: int               # 0-100, set by the scorer tool
    score_reason: str        # why Claude gave that score
    email_draft: str         # personalized cold email, written by Claude
    linkedin_url: str        # optional, found during search


def merge_leads(left: List[Lead], right: List[Lead]) -> List[Lead]:
    """
    Merges two lists of leads, deduplicating by website URL.
    When a lead exists in both, the 'right' (newer) one overwrites the 'left' one.
    This prevents leads from duplicating during state updates.
    """
    merged = {lead.get("website", ""): lead for lead in left}
    for lead in right:
        url = lead.get("website", "")
        if url:
            merged[url] = lead
    return list(merged.values())


class AgentState(TypedDict):
    """
    The full state of the agent at any point in the workflow.
    LangGraph passes this dict between every node automatically.
    """

    # ── Input (set once by the user via Streamlit) ──
    target_industry: str     # e.g. "SaaS companies in HR tech"
    icp_description: str     # Ideal Customer Profile — who we want to reach
    num_leads: int           # how many leads to find (e.g. 10)

    # ── Running state (updated by tools as agent works) ──
    leads: Annotated[List[Lead], merge_leads]  # uses custom reducer to merge by URL
    search_queries: List[str]   # queries already tried (avoid repeating)
    errors: List[str]           # non-fatal errors logged during run

    # ── Output flags ──
    is_complete: bool        # True when agent has enough leads
    final_summary: str       # human-readable summary shown in Streamlit