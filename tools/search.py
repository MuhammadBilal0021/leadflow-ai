"""Discover candidates while preserving profile identity and source provenance."""
from datetime import datetime, timezone
import os
import requests
from urllib.parse import urlsplit
from tavily import TavilyClient
from agent.runtime import check_run, count_usage
from tools.urls import clean_url, profile_kind, company_key


def build_search_queries(target_industry, icp_description):
    # Keep the actual ICP, including countries and constraints the old heuristics lost.
    return [
        f'{target_industry} {icp_description} company about',
        f'{target_industry} {icp_description} startup funding employees',
        f'site:crunchbase.com/organization/ {target_industry} {icp_description}',
        f'site:linkedin.com/company/ {target_industry} {icp_description}',
    ]


def search_companies(target_industry, icp_description, already_searched, num_results=10):
    if not 1 <= num_results <= 20:
        raise ValueError("Lead count must be between 1 and 20")
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("Live search is not configured")
    queries = [q for q in build_search_queries(target_industry, icp_description)
               if q not in already_searched]
    candidates, used, failures = {}, [], 0
    with requests.Session() as session:
        client = TavilyClient(api_key=key, session=session)
        for query in queries:
            check_run()
            count_usage(search_requests=1)
            try:
                response = client.search(query=query, search_depth="basic", max_results=10,
                    include_usage=True, timeout=12, exclude_domains=[
                        "reddit.com", "quora.com", "youtube.com", "g2.com", "capterra.com"])
                used.append(query)
                count_usage(search_credits=(response.get("usage") or {}).get("credits", 0))
            except Exception:
                check_run()
                failures += 1
                continue
            for raw in response.get("results", []):
                try:
                    url = clean_url(raw.get("url", ""))
                    kind = profile_kind(url)
                    if kind == "directory":
                        continue
                    title = str(raw.get("title", ""))[:200]
                    if any(term in title.lower() for term in ["top ", "best ", "list of", " vs ", "alternatives"]):
                        continue
                    if not kind and any(part in urlsplit(url).path.lower() for part in ["/blog/", "/news/", "/guides/"]):
                        continue
                    identity = company_key(url)
                except (ValueError, UnicodeError):
                    continue
                source = {"url": url, "text": str(raw.get("content", ""))[:5000],
                          "kind": "search_snippet", "retrieved_at": datetime.now(timezone.utc).isoformat()}
                if identity in candidates:
                    sources = candidates[identity]["additional_sources"]
                    if len(sources) < 2 and all(s["url"] != url for s in sources) and candidates[identity]["url"] != url:
                        sources.append(source)
                else:
                    candidates[identity] = dict(url=url, title=title, content=source["text"],
                        retrieved_at=source["retrieved_at"], additional_sources=[])
    check_run()
    return {"results": list(candidates.values())[:num_results], "queries_used": used,
            "warnings": [f"{failures} search queries were unavailable."] if failures else [],
            "error": "Search provider unavailable. Try again later." if queries and not used else None}


def extract_company_info(raw):
    url = clean_url(raw["url"])
    kind = profile_kind(url)
    title = raw.get("title", "") or "Unknown company"
    name = title
    for sep in [" | ", " - ", " :: "]:
        name = name.split(sep)[0]
    if kind in {"crunchbase.com", "linkedin.com"}:
        name = urlsplit(url).path.strip("/").split("/")[1].replace("-", " ").title()
    sources = [{"url": url, "text": raw.get("content", "")[:5000], "kind": "search_snippet",
                "retrieved_at": raw.get("retrieved_at", datetime.now(timezone.utc).isoformat())}]
    sources.extend(raw.get("additional_sources", [])[:2])
    sources = [dict(source, id=f"s{i}") for i, source in enumerate(sources)]
    return {"id": company_key(url), "company_name": name.strip()[:200],
            "website": "" if kind else url, "profile_url": url if kind else "",
            "linkedin_url": url if kind == "linkedin.com" else "", "description": sources[0]["text"][:600],
            "sources": sources, "score": None, "score_reason": "", "qualification_status": "needs_review",
            "scoring_status": "pending", "email_status": "not_requested", "email_draft": ""}
