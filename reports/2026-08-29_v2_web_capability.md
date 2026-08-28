# Web: search, fetch and visual view

Roadmap queue 1, last item. Implemented and accepted in the local profile;
nothing is deployed and no worker was started. The decision this builds is in
`ROADMAP.md` and `reports/2026-08-29_v2_web_capability_options.md`.

## What exists now

Three tools, because they are three different acts with three different costs.

| tool | what it does | cost | runs page code |
|---|---|---|---|
| `search_web` | Firecrawl ranked links, no page read | 2 provider credits | no |
| `fetch_page` | our own bounded HTTP GET, page as text | nothing | no |
| `view_web_page` | a real browser, text + screenshot | CPU seconds | **yes** |

- `app/web.py` — destination checking, the bounded fetch, the Firecrawl client,
  and both renderer placements.
- `app/tools/web.py` — the three tools. `view_web_page` saves its screenshot in
  the person's workspace and returns the path; it sends nothing. Presentation
  stays the separate `send_file` decision, unchanged from the previous item.
- `app/tools/chromium.py` — the browser process and the DevTools session, split
  out of `browser.py` so `inspect_page` and `view_web_page` share one
  implementation. `inspect_page` still blocks every network scheme; the split
  changed no behaviour and its tests were untouched.
- Three capabilities — `web.search`, `web.fetch`, `web.view` — so a grant can
  withhold the one that spends someone's allowance. Search is absent from the
  toolbox entirely when no key is configured, rather than present and failing.
- `deploy/modal/control_app.py` gains `render_web_page`: a CPU function with no
  secret, no database URL and no workspace volume, behind Modal proxy auth.

## Where a request may go

Every destination is resolved and checked before the connection and again on
every redirect: only `http`/`https`, only ports 80 and 443, no credentials in
the URL, and every address a name resolves to must be public. Loopback,
private, link-local, multicast, reserved, unspecified and IPv4-mapped forms are
refused, which is what keeps `169.254.169.254` — the address that hands out
cloud credentials to anything that asks — out of reach.

Bounds: 3 redirects, 20 s per wait **and 45 s for the whole call**, 1 MB, and a
content-type allow list of readable text formats. A body over the cap is cut and
the tool result says it was cut. The overall deadline exists because httpx
bounds individual waits, which a server satisfies indefinitely by sending one
small chunk at a time.

`fetch_page` **connects to the address the name was validated at**, carrying the
original `Host` and the TLS server name — so certificate verification still
happens against the real hostname and only the routing is pinned. A resolver
that answers differently between the check and the connection therefore changes
nothing, which is what closes DNS rebinding for the fetch path. Verified live
against a real HTTPS site.

`is_global` is consulted as well as the named properties. Neither is sufficient
alone: 100.64.0.0/10 — carrier-grade NAT, where a provider's own infrastructure
lives — answers `False` to `is_private`, and 224.0.0.1 answers `True` to
`is_global` while being multicast.

Everything returned is labelled untrusted in the tool result, and the capability
brief says the same about the whole capability. That is a mitigation, not a
solution; the harness rule in `AGENTS.md` is what actually decides it, and it
has still never been tested against a real adversary.

## What the browser is allowed to request

Checking the URL the caller asked for says nothing about what the browser does
next. It follows the page's own redirects, runs its scripts and loads its
subresources, and every one of those is a request to an address nobody checked.

So every request the browser makes is intercepted through CDP `Fetch` and put
through the same destination check; a refused one is failed with `AccessDenied`
and reported to the agent as a fact about the page. The browser's own
`about:`/`data:`/`blob:` URLs pass without a lookup. `inspect_page` passes no
policy and keeps blocking every network scheme outright, which is stricter.

Verified live: `https://httpbin.org/redirect-to?url=http://169.254.169.254/...`
fails with `net::ERR_ACCESS_DENIED` instead of loading, and pages with real
subresource trees (modal.com docs, news.ycombinator.com) render unchanged.

**Not closed:** Chromium resolves names itself, so the rebinding window that
pinning closes for `fetch_page` remains open for the browser — it cannot be
closed from outside the process. It is one more reason the renderer is the
container that holds nothing.

## Where the browser runs

`render_page` chooses by configuration, not by profile: a configured
`WEB_RENDERER_URL` goes to the isolated function, otherwise the page opens in
the local browser.

The third case is the one that needed code. A deployment that simply *forgot*
the renderer URL would have fallen back to its own browser — a stranger's
JavaScript in the container holding `TELEGRAM_TOKEN`, `MODEL_API_KEY` and
`AGENT_DATABASE_URL`, with nothing looking wrong. So the environment states
whether it may open a page itself: the deployed agent image carries
`WEB_LOCAL_BROWSER=0`, and a missing renderer there is a loud failure in
`/check` instead of a silent loss of the boundary. A first attempt inferred this
from `AGENT_DATABASE_URL` being set and was wrong on this machine, whose local
`.env` holds the Neon URL.

## Measured

Local profile, Windows, Edge; the deployed numbers do not exist yet.

| | |
|---|---:|
| `fetch_page` example.com | 0.47-0.81 s |
| `view_web_page` example.com, cold browser | 2.1 s, 13,259-byte PNG |
| `render_locally` modal.com docs, with subresources | 5.7 s, 8,000 chars, 201 KB PNG |
| `render_locally` news.ycombinator.com | 3.9 s, 4,098 chars, 122 KB PNG |
| `search_web`, 3 results | 1.91 s |

`/check` in the local profile: **9/9 free**, and **1/1** for the credit-costing
search probe asked for separately. That includes `web.fetch` and `web.view`
against a real public page, so it is egress and a real browser, not a mock.

### What running it caught

Two defects, neither visible in the code and neither found by a passing suite.

`web.fetch` and `web.search` first reported `FAIL ... tool is async; use
Toolbox.run_async`: the probe helper ran tools synchronously, so two working
tools were reported broken. Fixed by giving `tool_probes` an async path.

Then, after request interception was added, every rendered page came back with a
200 KB screenshot and **no text and no title**. The interception path allocated
its CDP message id by incrementing before sending while `call` incremented
after, so the acknowledgement of a `Fetch.continueRequest` carried the id the
next real call was waiting on, and the page's evidence arrived as an empty
dictionary. One counter, one rule, plus a regression test.

The second one matters beyond itself: `web.view` passed while it was happening,
because the probe only checked that a PNG came back. It now also requires the
page's text, which is what a probe of "can it read a web page" should always
have asserted.

### A page that refuses this client

Wikipedia answers a browser-shaped User-Agent with HTTP 403 and text asking the
client to identify itself. Measured, same URL, same network:

| identity | result |
|---|---|
| Chrome string | 403 |
| `curl/8.5.0`, or no agent | 403 |
| descriptive, no contact | 403 |
| `name/version (contact)` | 200, 441 KB |

Five other sites (modal.com, docs.python.org, news.ycombinator.com,
firecrawl.dev, habr.com) returned 200 with the browser string, and extra
browser-shaped headers changed nothing anywhere. So the default stays
browser-shaped, and `WEB_FALLBACK_USER_AGENT` — empty by default, because
inventing a contact address for the owner would be worse than the refusal —
adds one retry with a self-identifying agent when a site answers 403. The
refusal message names the setting. Firecrawl scrape remains the documented
fallback for pages neither identity can read; it is not implemented, because
nothing has needed it yet.

## Cost

Four Firecrawl credits of the renewing 1,000/month: two for the live search
check, two for the credit-gated probe run. Nothing else was spent — no GPU, no
deploy, no container.

## The deploy

`assistant-control` deployed 2026-08-29 in 41.6 s, CPU only; the model app was
not touched. `render_web_page` exists at
`https://grigoriy-v--assistant-control-render-web-page.modal.run`, marked by
Modal's own output as requiring proxy auth. The deploy started no container.

The Modal CLI first aborted with `'charmap' codec can't encode '→'` — a
Windows console encoding failure printing Modal's build output, not a deploy
failure. `PYTHONIOENCODING=utf-8` is the fix and belongs in front of any `modal`
command run from this machine.

**The browser layer's cache question is still open.** This deploy rebuilt it,
correctly: `uv.lock` changed (it was missing `pillow`, which `pyproject.toml`
already declared), and the lock is below the browser in the image, so everything
above it was invalidated. The next source-only deploy is the first honest
measurement.

## Not verified

- **`render_web_page` has never run.** Its cold latency, whether Chromium keeps
  its own sandbox under a non-root user there, and whether cloud metadata is
  reachable from it remain open questions from the options report.
- The deployed assistant right now fetches pages, has no search tool, and fails
  `view_web_page` by design: the three `WEB_` values are not in the
  `assistant-control` secret. Adding them is the owner's action — a partial
  `modal secret create --force` would replace the whole secret, dropping the bot
  token, the model key and the database URL.
- No live Telegram turn has used any of this, so the agent's *choice* of tool —
  search versus fetch versus view — is untested against a real model.

## Review, and what it changed

Five findings were raised against the first version of this work; all five were
accepted and fixed here.

| | fix |
|---|---|
| P1 `fetch_page` handed the name to httpx after checking it, and 100.64.0.0/10 was accepted | pinned connections with `Host`/SNI preserved, `is_global` added |
| P1 the browser checked only the first URL | CDP `Fetch` interception on every request, redirects included |
| P2 20 s bounded each wait, not the call | one `asyncio.timeout` around the whole fetch loop |
| P2 the system prompt advertised web tools a grant can withhold | the guidance moved into the generated capability brief |
| P3 `MAX_VIEWS_KEPT` was declared and never applied | oldest screenshots pruned, the newest one protected |

The prompt change has a consequence worth stating: the test that required every
wired tool to be named in `DEFAULT_SYSTEM_PROMPT` now requires it to be guided
by the prompt *or* the brief. A tool a grant can withhold cannot be named in a
fixed prompt without lying to an agent that does not have it.

## Checks

- `uv run pytest -q`: 613 passed, 1 skipped, offline, no network.
- `uv run ruff check` on every changed file: clean.
- Local `/can` lists the new tools; local `/check` 9/9 free and 1/1 credit,
  re-run after every change above.
- Live: HTTPS fetch through a pinned connection, three real pages rendered with
  interception on, and a redirect into the metadata address denied.

## The next human gates

1. Deploy `assistant-control` (starts nothing by itself, but every later call
   starts a worker), take the `render_web_page` URL.
2. Put `WEB_FIRECRAWL_API_KEY`, `WEB_RENDERER_URL` and `WEB_RENDERER_KEY` into
   the `assistant-control` Modal secret; redeploy.
3. Run the deployed self-test once with `include_credit=True` — this starts a
   worker and a renderer container.
4. One live Telegram turn that needs the web, to see the agent choose.
