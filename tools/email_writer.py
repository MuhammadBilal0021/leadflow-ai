# tools/email_writer.py
# ─────────────────────────────────────────────────────────────
# Takes a scored Lead and writes a personalized cold email.
# Only runs on leads that scored above a threshold (default 60)
# so we don't waste API calls on bad fits.,
#
# Test standalone:
#   python tools/email_writer.py
# ─────────────────────────────────────────────────────────────

import os
import json
from groq import Groq
from dotenv import load_dotenv
from typing import Dict
import time

load_dotenv()

# Configure Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Only write emails for leads above this score — saves API calls
# Set to 40 during testing to see more results; raise to 60 in production
SCORE_THRESHOLD = 40


def write_email(company: Dict, icp_description: str, sender_context: str) -> Dict:
    """
    Writes a personalized cold outreach email for a single lead using Groq.

    Input:
        company        — a scored Lead dict
        icp_description — used to understand what problem we're solving
        sender_context  — who is sending this email and what they offer
                          e.g. "I build AI automation tools for HR teams"

    Returns the same company dict with email_draft filled in.
    """

    # Skip low-scoring leads — don't waste tokens
    if company.get("score", 0) < SCORE_THRESHOLD:
        company["email_draft"] = f"Skipped — score {company['score']} below threshold {SCORE_THRESHOLD}"
        return company

    prompt = f"""You are an expert B2B cold email copywriter.

Write a short, personalized cold outreach email based on this context.

Sender context (who is reaching out):
{sender_context}

Target company:
Name: {company.get('company_name', 'there')}
Website: {company.get('website', '')}
Description: {company.get('description', '')}
Why they are a good fit: {company.get('score_reason', '')}

Email rules:
- Subject line must be specific to this company, not generic
- Opening line must reference something real about the company
- Body: 2-3 sentences MAX — busy people don't read long emails
- One clear call to action (e.g. "Would you be open to a 15-min call?")
- Tone: direct, human, no buzzwords, no "I hope this email finds you well"
- Do NOT use placeholders like [Your Name] — write it as a complete email

Respond ONLY with valid JSON. No text outside the JSON.
{{
  "subject": "<email subject line>",
  "body": "<full email body, use \\n for line breaks>"
}}"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )

            raw = response.choices[0].message.content.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)

            subject = result.get("subject", "Quick question")
            body = result.get("body", "")

            # Format as a complete readable email
            company["email_draft"] = f"Subject: {subject}\n\n{body}"
            break

        except json.JSONDecodeError:
            company["email_draft"] = "Error: Could not parse email — regenerate manually"
            break

        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)
                print(f"\n  [Rate limit hit, retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})]")
                time.sleep(wait_time)
                continue
            company["email_draft"] = f"Error: {str(e)}"
            break

    return company


def write_all_emails(leads: list, icp_description: str, sender_context: str) -> list:
    """
    Writes emails for all qualifying leads.
    Called by the LangGraph email writing node.
    """
    for i, lead in enumerate(leads):
        if lead.get("score", 0) >= SCORE_THRESHOLD:
            print(f"  Writing email for: {lead.get('company_name', '?')} (score: {lead['score']})")
            leads[i] = write_email(lead, icp_description, sender_context)
            time.sleep(1)  # rate limit protection
        else:
            print(f"  Skipping: {lead.get('company_name', '?')} (score: {lead['score']} — below threshold)")
            leads[i]["email_draft"] = "Skipped — score too low"

    return leads


# ── Standalone test — run: python tools/email_writer.py ──
if __name__ == "__main__":
    print("Testing email writer tool...\n")

    # Same fake lead from scorer.py — now with a score filled in
    test_lead = {
        "company_name": "HireFlow",
        "website": "https://hireflow.io",
        "description": "HireFlow is a US-based HR tech SaaS helping mid-size companies automate their hiring pipeline. Founded in 2021, 80 employees, Series A funded.",
        "linkedin_url": "https://linkedin.com/company/hireflow",
        "score": 90,
        "score_reason": "US-based HR tech SaaS with 80 employees and Series A — matches ICP exactly.",
        "email_draft": "",
    }

    icp = "US-based SaaS companies in HR tech, 50-200 employees, Series A or B funded"
    sender = "I build AI-powered automation tools that help HR SaaS companies reduce manual ops by 60%"

    result = write_email(test_lead, icp, sender)

    print(result["email_draft"])