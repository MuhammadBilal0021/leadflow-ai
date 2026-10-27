"""Sequential stages replace lead lists so score ordering is preserved."""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    target_industry: str
    icp_description: str
    qualification_criteria: list[str]
    sender_context: str
    num_leads: int
    leads: list[dict]
    search_queries: list[str]
    errors: list[str]
    is_complete: bool
    final_summary: str
    status: str
