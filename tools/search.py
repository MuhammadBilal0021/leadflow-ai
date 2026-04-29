# tools/search.py
# -----------------------------------------------------------------
# Searches for real companies matching a target industry + ICP.
# Uses Tavily API with multiple query strategies including
# Crunchbase-targeted queries to get funding/employee data.
#
# Test standalone:
#   python tools/search.py
# -----------------------------------------------------------------

import os
from tavily import TavilyClient
from dotenv import load_dotenv
from typing import List, Dict
from urllib.parse import urlparse

load_dotenv()

tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


# -- Query templates designed to land on REAL company pages --
QUERY_TEMPLATES = [
    # Crunchbase queries — rich with funding + employee data
    'site:crunchbase.com {industry} company {location}',
    'site:crunchbase.com {industry} startup {funding}',
    # Direct company pages — pricing, about, demo pages
    '{industry} software company {location} "about us"',
    '{industry} platform for {size} companies pricing',
    '{industry} SaaS startup {location} careers',
    # LinkedIn company pages — good for size/industry info
    'site:linkedin.com/company {industry} {location}',
]


def build_search_queries(target_industry: str, icp_description: str) -> List[str]:
    """
    Generates multiple varied queries using templates.
    Extracts size, location, and funding hints from the ICP.
    """
    # Extract size hint
    size = "small business"
    if "50-200" in icp_description or "mid" in icp_description.lower():
        size = "mid-size"
    elif "enterprise" in icp_description.lower():
        size = "enterprise"

    # Extract location hint
    location = ""
    if "us-based" in icp_description.lower() or "united states" in icp_description.lower():
        location = "United States"
    elif "uk" in icp_description.lower():
        location = "United Kingdom"

    # Extract funding hint
    funding = ""
    if "series a" in icp_description.lower():
        funding = "Series A"
    elif "series b" in icp_description.lower():
        funding = "Series B"
    if "series a or b" in icp_description.lower():
        funding = "Series A Series B"

    queries = []
    for template in QUERY_TEMPLATES:
        q = template.format(
            industry=target_industry,
            size=size,
            location=location,
            funding=funding,
        )
        # Clean up double spaces from empty placeholders
        q = " ".join(q.split())
        queries.append(q)

    return queries


def _extract_domain(url: str) -> str:
    """Extracts the root domain from a URL for dedup."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Strip www.
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url


def search_companies(
    target_industry: str,
    icp_description: str,
    already_searched: List[str],
    num_results: int = 10,
) -> Dict:
    """
    Runs multiple focused queries and merges results.
    Filters out listicles, blog posts, and non-company pages.
    Deduplicates by root domain so we don't get 3 pages from the same company.
    """
    queries = build_search_queries(target_industry, icp_description)

    # Skip queries already tried this run
    queries = [q for q in queries if q not in already_searched]
    if not queries:
        queries = [f"{target_industry} software company about us careers"]

    all_results = []
    queries_used = []

    for query in queries:
        try:
            response = tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                exclude_domains=[
                    "reddit.com", "quora.com", "wikipedia.org",
                    "youtube.com", "twitter.com", "x.com",
                    "techcrunch.com", "forbes.com", "businessinsider.com",
                    "venturebeat.com",
                    # Review/aggregator sites (not real companies)
                    "g2.com", "capterra.com", "getapp.com",
                    "softwareadvice.com", "trustradius.com",
                    # Dev/listicle sites
                    "datamation.com", "omnius.so", "belitsoft.com",
                    "medium.com", "substack.com",
                ],
            )
            results = response.get("results", [])
            all_results.extend(results)
            queries_used.append(query)

        except Exception as e:
            print(f"  [Search] Query failed: {query[:50]}... -> {e}")
            continue

    if not all_results:
        return {
            "results": [],
            "queries_used": queries_used,
            "error": "All search queries failed or returned no results",
        }

    # ------ FILTERING ------

    # Title-based listicle filter
    listicle_keywords = [
        "top ", "best ", "leading ", "list of", "companies to know",
        "startups to watch", "most successful", "roundup", " vs ",
        "comparison", "alternatives",
    ]

    # URL-based blog filter (but EXEMPT crunchbase and linkedin)
    blog_url_indicators = [
        "/blog/", "/article/", "/news/", "/press/", "/resources/",
        "/guides/", "/guide/", "blog.", "news.", "/post/", "/story/",
    ]
    # These domains are ALWAYS useful even if they have /blog-like paths
    trusted_domains = ["crunchbase.com", "linkedin.com"]

    # Title-based noise filter — these are articles, not companies
    article_title_keywords = [
        "guide ", "how to ", "what is ", "what are ", "essentials for",
        "tips for", " ways to", "a guide", "the guide", "the complete",
    ]

    filtered = []
    for r in all_results:
        title = r.get("title", "").lower()
        url = r.get("url", "").lower()
        domain = _extract_domain(url)

        is_listicle = any(kw in title for kw in listicle_keywords)
        is_article = any(kw in title for kw in article_title_keywords)
        is_trusted = any(td in domain for td in trusted_domains)
        is_blog = any(ind in url for ind in blog_url_indicators) and not is_trusted

        if not is_listicle and not is_blog and not is_article:
            filtered.append(r)

    # Deduplicate by root domain (so factorialhr.com/pricing and factorialhr.com/about count as one)
    seen_domains = set()
    unique_results = []
    for r in filtered:
        domain = _extract_domain(r.get("url", ""))
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            unique_results.append(r)

    # Trim to requested number
    unique_results = unique_results[:num_results]

    print(f"[Search] Ran {len(queries_used)} queries -> {len(all_results)} raw -> {len(filtered)} filtered -> {len(unique_results)} unique")

    return {
        "results": unique_results,
        "queries_used": queries_used,
        "error": None,
    }


def extract_company_info(tavily_result: Dict) -> Dict:
    """
    Converts a raw Tavily search result into our Lead dict format.
    Extracts company name from the page title (splitting on common separators).
    """
    url = tavily_result.get("url", "")
    title = tavily_result.get("title", "")
    content = tavily_result.get("content", "")

    # Extract company name — handle Crunchbase format "Company - Crunchbase"
    company_name = title
    for sep in [" | ", " - ", " -- ", " :: "]:
        if sep in company_name:
            company_name = company_name.split(sep)[0]
            break
    company_name = company_name.strip()

    # For Crunchbase, the URL slug is often cleaner
    if "crunchbase.com/organization/" in url:
        slug = url.split("/organization/")[-1].split("/")[0].split("#")[0]
        # Convert slug to title case: "hire-flow" -> "Hire Flow"
        company_name = slug.replace("-", " ").title()

    linkedin_url = url if "linkedin.com/company" in url else ""

    # For LinkedIn, extract company name from URL slug
    if "linkedin.com/company/" in url and company_name == title:
        slug = url.split("/company/")[-1].split("/")[0]
        company_name = slug.replace("-", " ").title()

    return {
        "company_name": company_name,
        "website": url,
        "description": content[:600],
        "linkedin_url": linkedin_url,
        "score": 0,
        "score_reason": "",
        "email_draft": "",
    }


if __name__ == "__main__":
    print("Testing search tool...\n")

    result = search_companies(
        target_industry="HR tech SaaS",
        icp_description="US-based, 50-200 employees, Series A or B funded",
        already_searched=[],
        num_results=10,
    )

    if result["error"]:
        print(f"Error: {result['error']}")
    else:
        print(f"\nFound {len(result['results'])} results after filtering:\n")
        for r in result["results"]:
            company = extract_company_info(r)
            print(f"  Company : {company['company_name']}")
            print(f"  URL     : {company['website']}")
            print(f"  Snippet : {company['description'][:120]}...")
            print()