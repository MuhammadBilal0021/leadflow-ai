# Security boundaries and remaining limits

## Implemented controls

| Risk | Control |
| --- | --- |
| Untrusted result HTML | Text nodes and DOM properties; no dynamic HTML or inline event handlers; CSP |
| Internal-network scraping | Strict URL syntax, public-address checks on every DNS result and redirect, connections pinned to checked IP, preserved TLS SNI and hostname validation |
| Oversized/slow scraping | Standard ports only, redirect cap, bounded body, identity encoding, connect/read limits and cooperative deadlines |
| API spending abuse | Explicit live token, bounded inputs, per-session/IP quotas, shared daily start budget, two active workers |
| Cross-run log leakage | Explicit per-run events and ContextVar usage; no stdout replacement |
| Cross-session report access | Random session capability, hashed storage, HttpOnly SameSite cookie, owner-scoped SQL |
| Prompt/output manipulation | Untrusted-source system instructions, strict schemas, exact-quote validation, fail-closed scoring and human review |
| CSV formula execution | Formula/control-prefix escaping before CSV serialization |
| Provider secret exposure | Generic streamed errors; report inputs exclude credentials |
| Dependency advisories | Reduced direct dependencies, pinned runtime closure and CI advisory scan |

## Important limits

Prompt separation and quote validation reduce risk; they do not eliminate prompt injection or incorrect reasoning. A malicious page could contain persuasive but false statements. Quote validation is not semantic verification. Email text remains model-generated, so human review is required.

Company directory profiles are retained as profiles. Cross-domain identity resolution and independent verification are future work. Funding and headcount can become stale. Search snippets may be truncated or inaccurate; their source kind and retrieval time are visible.

Anonymous sessions are browser capabilities, not named accounts. Losing cookies loses access to saved reports. An administrator with database access can read all reports. Serve behind HTTPS with Secure cookies when deployed; use filesystem permissions/backups appropriate to the database's contents.

Application quotas do not replace edge protection against denial of service. Single-process worker limits must not be bypassed with multiple Uvicorn workers. Proxy clients intentionally share the proxy IP bucket. Session count and retained reports are bounded, but an exposed anonymous service can still be disrupted. Use an authenticated reverse proxy for an internet-facing installation.

Cancellation is cooperative. Existing provider calls and OS DNS resolution may finish after a disconnect/deadline; no further calls are scheduled after cancellation is observed. For hard deadlines and more robust isolation, move jobs into supervised worker processes.

Scraping does not execute JavaScript, follow page instructions, or load images/subresources. Websites that require browser rendering, compression or bot challenges may remain unenriched; the app keeps the search evidence and marks enrichment unavailable.

No automated contact discovery, verified email delivery, CRM integration, or automatic sending is implemented. Review applicable provider terms and outreach requirements before extending those features.

## Verification

Regression tests cover unsafe URL schemes, mixed public/private DNS, loopback redirects, IP/TLS pinning, body limits, untrusted DOM content, invalid model outputs, invented citations, ownership isolation, quota enforcement, cancellation and shared-loop responsiveness. CI checks runtime pins against public advisories; this does not guarantee the absence of undisclosed vulnerabilities.

The original large requirements snapshot was replaced. LangGraph/SDK and urllib3 were upgraded after the initial audit identified known advisories. See the dated verification report for the final scan result.
