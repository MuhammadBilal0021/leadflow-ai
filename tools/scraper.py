# tools/scraper.py
# -----------------------------------------------------------------
# Fetches a company's homepage and extracts a clean text summary.
# Used to ENRICH lead descriptions before scoring so the scorer
# has real company info (not just a search snippet).
#
# Test standalone:
#   python tools/scraper.py
# -----------------------------------------------------------------

import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional


# Pages we specifically want to try scraping (in priority order)
USEFUL_PATHS = ["/about", "/about-us", "/company", ""]


def scrape_company_page(url: str, timeout: int = 8) -> Optional[str]:
    """
    Fetches a URL and extracts clean text content from the page.
    Returns up to 800 chars of meaningful text, or None on failure.
    """
    try:
        # Normalize URL to root domain
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        best_text = ""

        for path in USEFUL_PATHS:
            try:
                target = base_url + path
                resp = requests.get(
                    target,
                    timeout=timeout,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    },
                    allow_redirects=True,
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Remove scripts, styles, navs, footers
                for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
                    tag.decompose()

                # Try to get meta description first (usually the best summary)
                meta_desc = ""
                meta_tag = soup.find("meta", attrs={"name": "description"})
                if meta_tag and meta_tag.get("content"):
                    meta_desc = meta_tag["content"].strip()

                # Get the page title
                page_title = ""
                if soup.title and soup.title.string:
                    page_title = soup.title.string.strip()

                # Get body text
                body_text = soup.get_text(separator=" ", strip=True)
                # Clean up excessive whitespace
                body_text = " ".join(body_text.split())

                # Build the enriched description
                parts = []
                if page_title:
                    parts.append(f"Company: {page_title}.")
                if meta_desc:
                    parts.append(f"About: {meta_desc}")
                if body_text:
                    # Take meaningful body text (skip very short pages)
                    if len(body_text) > 50:
                        parts.append(f"Details: {body_text[:500]}")

                combined = " ".join(parts)

                # Keep the longest/richest result we find across paths
                if len(combined) > len(best_text):
                    best_text = combined

                # If we got a good result from /about, stop early
                if path in ["/about", "/about-us", "/company"] and len(combined) > 200:
                    break

            except Exception:
                continue

        return best_text[:800] if best_text else None

    except Exception as e:
        print(f"  [Scraper] Failed for {url}: {e}")
        return None


def enrich_lead(lead: Dict) -> Dict:
    """
    Enriches a single lead's description by scraping its website.
    If scraping fails, keeps the original description.
    """
    url = lead.get("website", "")
    if not url:
        return lead

    original_desc = lead.get("description", "")
    print(f"  [Scraper] Enriching: {lead.get('company_name', '?')} ({url})")

    scraped = scrape_company_page(url)

    if scraped and len(scraped) > len(original_desc):
        # Combine: keep original snippet + add scraped context
        lead["description"] = f"{original_desc}\n\n--- Scraped from website ---\n{scraped}"
        print(f"  [Scraper] Enriched with {len(scraped)} chars of website content")
    else:
        print(f"  [Scraper] No improvement found, keeping original description")

    return lead


def enrich_all_leads(leads: list) -> list:
    """
    Enriches all leads in the list. Called by the LangGraph enrich node.
    """
    enriched = []
    for lead in leads:
        enriched.append(enrich_lead(lead))
    return enriched


# -- Standalone test -- run: python tools/scraper.py --
if __name__ == "__main__":
    print("Testing scraper tool...\n")

    test_url = "https://factorialhr.com"
    print(f"Scraping: {test_url}\n")

    result = scrape_company_page(test_url)
    if result:
        print(f"Got {len(result)} chars:\n")
        print(result)
    else:
        print("Scraping failed or returned no content.")
