# Web capability: providers, costs and isolation options

Research behind roadmap queue 2. Options and reasoning, not approved work —
what the human decided is in `ROADMAP.md` and nothing here overrides it.

## What was decided

Search first, through Firecrawl, whose account already exists. Scrape laid in
as a tool rather than a default. Rendering a page done by us, in the tool
sandbox. Everything below is the material that decision was made against.

## Search providers

| | latency | free | paid |
|---|---:|---|---|
| Brave | ~669 ms | $5 credit/month = 1,000 queries | $5 / 1,000 |
| Firecrawl | seconds when scraping | 1,000 credits/month, renewing | plans from $16/month |
| Tavily | 5 s+ on advanced tiers | 1,000 queries/month | $0.008 / query |
| Exa | — | first 10 results with text | — |

Brave is the fastest and an independent index rather than a reseller; it would
be the answer if search latency alone decided it. Firecrawl wins on scope: one
key covers search, fetch and screenshot, and the account exists.

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

## Isolation

The question is where untrusted pages are rendered.

Rendering in the update worker is not acceptable: that container holds
`AGENT_DATABASE_URL`, `TELEGRAM_TOKEN` and `MODEL_API_KEY` as environment
variables, and Chromium under `--no-sandbox` as root has no isolation of its
own, so a renderer exploit that reaches the container reads them.

Rendering in the tool sandbox is acceptable: a sandbox is created without the
control secret, so there is nothing of that kind to take. A separate secretless
Modal function was proposed and dropped as a parallel mechanism for a boundary
the sandbox already provides.

Two things remain true in the sandbox and are worth settling when it is built:

- The sandbox is where the user's workspace lives, so "no secrets" is not "no
  assets". A sandbox doing untrusted browsing need not have the workspace
  attached, and sandboxes are ephemeral anyway.
- `--no-sandbox` is a concession to running as root. It is harmless while the
  browser renders artifacts the agent itself wrote; for the open web, Chromium
  keeping its own sandbox as a non-root user removes most of the exploit path.
- Whether the cloud metadata address is reachable from a sandbox is a
  credential path unrelated to ours, and is one request to check.

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
