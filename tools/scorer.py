# tools/scorer.py
# ─────────────────────────────────────────────────────────────
# Takes a company (Lead) and uses Groq to score it 0-100
# based on how well it matches the user's ideal customer profile.
#
# Test standalone:
#   python tools/scorer.py
# ─────────────────────────────────────────────────────────────

import os
import json
from groq import Groq
from dotenv import load_dotenv
from typing import Dict
import time

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def score_lead(company: Dict, icp_description: str) -> Dict:
    """
    Scores a single lead against the ICP using Groq.

    Input:
        company        — a Lead dict (from search.py / state.py)
        icp_description — the user's plain-english ideal customer profile

    Returns the same company dict with score + score_reason filled in.
    """

    prompt = f"""You are a B2B sales expert. Score this company as a sales lead.

Ideal Customer Profile (ICP):
{icp_description}

Company to score:
Name: {company.get('company_name', 'Unknown')}
Website: {company.get('website', '')}
Description: {company.get('description', 'No description available')}

Score this company from 0 to 100 based on how well it matches the ICP.
- 80-100: Excellent fit, high priority
- 60-79:  Good fit, worth reaching out
- 40-59:  Partial fit, low priority
- 0-39:   Poor fit, skip

CRITICAL RULE: Information (like funding or employee count) may be missing because this is just a brief snippet. DO NOT assume it's a mismatch if information is missing. DO NOT penalize the score heavily for missing info. Only give a poor score (0-39) if the description explicitly CONTRADICTS the ICP (e.g., they are a marketing agency instead of HR SaaS, or based in Spain when looking for US).

Respond ONLY with valid JSON. No explanation outside the JSON.
{{
  "score": <integer 0-100>,
  "reason": "<one sentence explaining the score>"
}}"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )

            raw = response.choices[0].message.content.strip()

            # Just in case the model wraps in a codeblock
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)

            company["score"] = int(result.get("score", 0))
            company["score_reason"] = result.get("reason", "No reason provided")
            break

        except json.JSONDecodeError:
            # If the model returns something unparseable, give a neutral score
            company["score"] = 50
            company["score_reason"] = "Could not parse score — manual review needed"
            break

        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)
                print(f"\n  [Rate limit hit, retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})]")
                time.sleep(wait_time)
                continue
            company["score"] = 0
            company["score_reason"] = f"Scoring failed: {str(e)}"
            break

    return company


def score_all_leads(leads: list, icp_description: str) -> list:
    """
    Scores a list of leads and returns them sorted best-first.
    Called by the LangGraph scoring node.
    """
    scored = []
    for lead in leads:
        scored_lead = score_lead(lead, icp_description)
        scored.append(scored_lead)
        print(f"  Scored: {lead.get('company_name', '?')} -> {scored_lead['score']}/100")
        time.sleep(1)  # rate limit protection

    # Sort by score descending so best leads appear first
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ── Standalone test — run: python tools/scorer.py ──
if __name__ == "__main__":
    print("Testing scorer tool...\n")

    # Fake lead to test with (same shape as what search.py returns)
    test_lead = {
        "company_name": "HireFlow",
        "website": "https://hireflow.io",
        "description": "HireFlow is a US-based HR tech SaaS helping mid-size companies automate their hiring pipeline. Founded in 2021, 80 employees, Series A funded.",
        "linkedin_url": "https://linkedin.com/company/hireflow",
        "score": 0,
        "score_reason": "",
        "email_draft": "",
    }

    icp = "US-based SaaS companies in HR tech, 50-200 employees, Series A or B funded"

    print(f"Company : {test_lead['company_name']}")
    print(f"ICP     : {icp}\n")

    result = score_lead(test_lead, icp)

    print(f"Score  : {result['score']}/100")
    print(f"Reason : {result['score_reason']}")