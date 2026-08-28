# Web capability: providers, costs and isolation options

Research behind roadmap queue 1. Options and reasoning, not implementation authority —
what the human decided is in `ROADMAP.md` and nothing here overrides it.

## What was decided

The capability has three separate agent tools:

- search through Firecrawl, whose account already exists;
- `fetch_page`, our own bounded direct HTTP fetch, with no provider API or
  provider credit on its normal path;
- `view_web_page`, our Chromium renderer in a separate secretless CPU function
  with no workspace volume.

Firecrawl scrape is an explicit fallback for a page our datacenter fetch or
browser cannot read, never the default fetch path. A general-purpose Modal
Sandbox is not required for this capability. Everything below is the material
that decision was made against.

## Search providers

| | latency | free | paid |
|---|---:|---|---|
| Brave | ~669 ms | $5 credit/month = 1,000 queries | $5 / 1,000 |
| Firecrawl | seconds when scraping | 1,000 credits/month, renewing | plans from $16/month |
| Tavily | 5 s+ on advanced tiers | 1,000 queries/month | $0.008 / query |
| Exa | — | first 10 results with text | — |

Brave is the fastest and an independent index rather than a reseller; it would
be the answer if search latency alone decided it. Firecrawl is selected for
search because the account exists and its allowance is sufficient for the
initial product. Its ability to fetch and screenshot does not make those the
default paths: our own tools retain that control.

Keyless search was examined and rejected. DuckDuckGo's Instant Answer endpoint
returns abstracts, not ranked web results; MediaWiki is Wikipedia only; SearXNG
removes the key but not the hosting or the upstream blocking. Querying an
engine directly from a datacenter address returns bot challenges rather than
results, and defeating those is neither reliable nor something this project
will do.

If search latency turns out to matter, adding Brave behind the same interface
is the smallest change.

## Firecrawl credits

Free tier is 1,000 credits a month, renewing; credits do not roll over.

| | |
|---|---:|
| search, 10 results | 2 |
| scrape, per page | 1 |
| screenshot format | included in the scrape |
| JSON, question, highlights, PII redaction, audio, video | +4 each |
| PDF | 1 per page |

Free-plan rate limits: 10 searches/minute, 10 scrapes/minute.

So a search alone is 2 credits, and a search that also reads its top three
results is 5. Searching with `scrapeOptions` over ten results would be 12 and
would drive ten browsers, which is why scraping is not a default.

## Direct fetch

`fetch_page` performs a normal HTTP request in the existing agent worker. It
does not execute page JavaScript and therefore does not need another worker.
The implementation must bound time, redirects, response bytes and accepted
content types, and reject loopback, private, link-local and cloud-metadata
destinations after resolution and on every redirect. HTML becomes bounded
readable text for the agent. It is still untrusted model input.

## Visual-render isolation

The question is where untrusted pages are rendered.

Rendering in the update worker is not acceptable: that container holds
`AGENT_DATABASE_URL`, `TELEGRAM_TOKEN` and `MODEL_API_KEY` as environment
variables, and Chromium under `--no-sandbox` as root has no isolation of its
own, so a renderer exploit that reaches the container reads them.

The chosen boundary is a dedicated secretless CPU renderer function, not a
general execution sandbox. It receives only a validated public URL and bounded
render options; it has no control secret, model key, database URL or workspace
volume. It returns bounded visible text, final URL and screenshot bytes. The
calling agent worker may save the screenshot into the person's workspace, and
the agent separately chooses whether to present it with `send_file`.

This is smaller than a general Modal Sandbox and preserves the required product
outcome. The open questions to test when it is built are whether cloud metadata
is reachable, whether Chromium can retain its own sandbox under a non-root user,
and the cold latency of the extra CPU function.

Our own rendering runs from a datacenter address, which some sites answer with
a challenge page rather than content. Firecrawl's scrape is the fallback for
those, at 1 credit a page.

## Not covered by isolation

Everything a fetch or a render returns is untrusted input arriving in the same
context as the user's instructions. That is a harness problem, not a container
problem, and no boundary above addresses it. The rule exists in `AGENTS.md`;
it has never been enforced against a real adversary.

Asking a third party for a page also tells it what the user is reading. Zero
data retention is an enterprise term at Firecrawl, so the capability
description should say plainly that the fallback leaves the machine.
