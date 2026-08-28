# Capabilities: a browser, a workspace that survives, and documents

Roadmap queue 1. The browser, the persistent workspace and document reading are
**accepted**: deployed 2026-08-29, `/check` passing 6/6 inside the container, and
a real document read correctly in a real chat. Web access is not built and showed
itself in the same session.

## Two decisions the human approved, 2026-08-29

**A volume, not a sandbox, for persistence.** The sub-item read "file tools over
an ephemeral sandbox", which bundled two questions: does a file survive between
two messages, and where is untrusted content allowed to run. Only the second
needs a sandbox. A Modal volume mounted into the worker answers the first,
starts nothing and costs storage.

**A document is saved, not pasted.** It goes into the person's workspace and the
model reads it with `read_document`. The alternative — extracting text at
admission — would spend the context on a long PDF before the model had decided
which part of it mattered.

## Chromium

`agent_image = control_image.apt_install("chromium", fonts…)`. The worker and
`self_test` run on it; the webhook stays on the layer above, because it renders
nothing and it is the one function a person waits on.

Fonts are part of the capability, not a nicety: `debian_slim` ships none, and a
screenshot of Cyrillic text without them is a row of boxes.

`container_flags()` adds `--no-sandbox --disable-dev-shm-usage --disable-gpu`
when the process is root on a POSIX machine, and nothing otherwise. Chromium
refuses its own sandbox as root and a container's 64 MB `/dev/shm` crashes a
renderer rather than failing honestly. Both are facts about the machine, so they
are read from the machine. A desktop keeps the browser's sandbox: handing away
the only isolation the browser has, everywhere, so that one environment works
would make the container's concession the default.

## The workspace

One volume, `assistant-workspaces`, at `/workspaces`, with `AGENT_WORKSPACE` set
in the agent image. `user_workspace` still puts each person in their own
directory inside it, so one volume is not one workspace.

The turn reloads before and commits after. Not around the process: a container
lives as long as its idle window, so one that has been alive since before
another container's write would keep serving what it first saw, and the next
message would be answered against a stale workspace.

Untested until deployed: whether the reload and commit cost anything noticeable
on a turn, and whether two workers writing one person's directory ever collide.
The second is a narrower version of the serialization debt in queue 4.

## Documents

`app/documents.py` extracts labelled sections: page numbers for a PDF, headings
for Markdown and `.docx`, a row count for CSV. `.docx` tables come last because
python-docx exposes paragraphs and tables as two sequences and their true
interleaving is not available — guessing would put a label on a lie.

`read_document` returns bounded output and always says where it stopped and how
to continue. A tool result goes into the next request unasked, so a model cannot
decline what it has already been given, and one that is not told what it did not
see answers from a fragment believing it has the whole thing.

A scanned PDF fails with "no text layer … probably a scan" rather than "empty".
The difference is the person's next step.

Admission changed: `admit_uploads` sends media to the model as before and writes
documents into the workspace, adding one text part that names them. A sent
filename is treated as hostile — separators and `..` stripped — and a second
`report.pdf` becomes `report-2.pdf` rather than overwriting the first.

`/can` now has a `Read:` line, generated from the format table, and the free
`/check` gained a `documents.read` probe that runs a real parser: the libraries
are an optional dependency group, so an image built without them fails in a way
that is invisible offline and looks like "the document was empty" to whoever
sent one.

## Looking at a page instead of reading it

Approved 2026-08-29, after the question "can the agent open a PDF in the browser
and look at it instead of OCR".

The browser can. Tried locally against Edge in `--headless=new`: navigating to a
`file://` PDF and screenshotting returned the page with its text legible. It also
returned the viewer's toolbar, scrollbar and dark background, only page one, and
it needed `file://`, which `inspect_page` blocks on purpose. Whether Debian's
`chromium` package even ships the PDF viewer was never established.

So `view_pages` uses pypdfium2 — the same PDFium that renders PDFs inside Chrome,
as a library. A page becomes a PNG with nothing but the page in it, chosen by
number, identically in both profiles. The long side is 1400 px; a page of 11-point
body text rendered that way was read back and is legible.

There is no OCR step. The model is multimodal, so it looks at the page the way a
person does, and an illegible scan looks illegible rather than becoming confident
nonsense.

At most two pages per call. The server's limit is four images per prompt and a
turn may already carry the person's own photo and history media, so the cap is
enforced in the tool rather than hoped for in the schema.

`/check` gained `documents.view` alongside `documents.read`. All four free probes
pass locally: filesystem, browser.inspect, documents.read, documents.view.

## Accepted live, 2026-08-29

Deployed in 74.6 s. The volume `assistant-workspaces` was created by the deploy.

`/check` in the deployed container: **6 of 6 passed** — `store.turn`,
`store.memory`, `filesystem`, `browser.inspect`, `documents.read`,
`documents.view`. `browser.inspect` had been the standing failure this item
opened with, so Chromium in the image and the container launch flags are both
confirmed where they matter rather than on a laptop.

Then a real document: a PDF sent to the bot in Telegram was saved, read with
`read_document` and summarized correctly, with its structure intact. Nothing
about its content is recorded here; it was personal.

That is the whole chain working — Telegram file, workspace on a volume, tool
call, answer — and it is what the sub-items were for.

**A link.** The assistant answered that it cannot open external sites. Correct,
and the right shape of answer: it declined instead of inventing what was behind
the link. That is the remaining sub-item, not a defect.

**Asked to show the PDF it had just summarized**, it answered that it is a text
model with no way to display anything. That *was* a defect, and of the exact kind
`app/capabilities.py` was written to make impossible. Two causes, both found:

- The generated brief said documents "are read with read_document, **never shown
  to you directly**" and never mentioned `view_pages`. I wrote that sentence
  hours earlier, before the tool existed. The assistant repeated what it was
  told. Fixed in the brief, the tool description and the system prompt, all three
  of which now cover "the person asks you to look at or show it", and a test
  asserts the old sentence cannot come back.
- The image genuinely could not reach the person: `_deliver` returned early for
  any `tool` message, so a rendered page went to the model and stopped at the
  adapter. Now a tool's *media* is delivered while its text still is not —
  approved 2026-08-29. The same change makes a browser screenshot visible.

Worth naming: the honesty machinery did not fail, its input did. The brief is
generated from wiring precisely so it cannot be wrong, and it was wrong because
one sentence in it was still hand-written prose.

## State at handover, 2026-08-29

Written for whoever picks this up next. Everything here is a fact that was
checked, not a plan.

### Deployed

`assistant-control` **v14**, deployed 03:46, from the tree this commit records.
v13 at 03:16 was the version `/check` passed 6/6 against and the version that
read a real PDF correctly; v14 adds the defect fix, the tool-media delivery and
the image layer order.

### What v14 changed and what has not been retested against it

Everything below is written, tested offline and now deployed. None of it has
been exercised in a real chat, so none of it is accepted:

1. The capability brief, the system prompt and the `view_pages` description no
   longer claim a document cannot be seen. On v13 the assistant told a person it
   was a text model that could not display anything.
2. A tool message's media reaches the chat; its text still does not. This is
   what makes "show me the page" possible at all, and it also makes an
   `inspect_page` screenshot visible for the first time.
3. Chromium is installed below the copied source, so it is no longer reinstalled
   on every deploy. v14 paid the slow build once because the cache key moved;
   deploys after it should be fast until `uv.lock` changes. **Unconfirmed** —
   the next deploy is the measurement.

### Checks that were run

`pytest`: 538 passed, 1 skipped. Ruff clean on every changed file; two
pre-existing findings in `ui/chainlit_app.py` and `app/agent/task_graph.py` were
left alone. The four free preflight probes pass locally, and 6/6 passed in the
deployed container on v13.

### Decisions the human approved in words, 2026-08-29

Not drafts. `AGENTS.md`, Records, is the rule these are recorded under.

- A Modal volume for workspace persistence, and the sandbox kept only for
  untrusted content.
- A document is saved to the workspace and read with a tool, rather than
  extracted into the turn at admission.
- `view_pages` renders PDF pages with pypdfium2, not through the browser.
- A tool's media is delivered to the chat.
- The Firecrawl key is `WEB_FIRECRAWL_API_KEY`, under a `WebSettings` class with
  the `WEB_` prefix that does not exist yet. The human holds the key; it is in
  neither `.env` nor the Modal secret as far as this session knows.

### Open, and deliberately not done

- **Web access is not started.** It is the remaining sub-item, and it is what a
  person hits first: a link sent to the bot gets an honest refusal.
- **The sandbox is not started.** Rendering an arbitrary URL waits on it, because
  the worker holds `TELEGRAM_TOKEN`, `AGENT_DATABASE_URL` and `MODEL_API_KEY`.
- **`--no-install-recommends` was not used.** It would cut build time and image
  size further. Not taken because a missing recommend only shows up in a
  container, costing another slow deploy to discover; `/check` would catch it.
- **Nothing bounds how many pages reach the chat.** Two images per `view_pages`
  call, and a model reading a long scan would send a burst of photos. Not seen
  yet, not guarded.
- **Chainlit still refuses documents.** It admits uploads through
  `load_attachments`, which was not changed.
- **`app/agent/browser_verifier.py`** holds a second `find_chromium_browser` and
  its own launch flags, and never got the container flags. Reachable only from
  its own tests.
- The volume's `reload`/`commit` cost per turn is unmeasured, and two workers
  writing one person's directory has never been exercised. That is a narrower
  form of the serialization debt in queue 4.

## Checks that were run

`pytest`: 538 passed, 1 skipped. Ruff clean on every changed file; two
pre-existing findings in `ui/chainlit_app.py` and `app/agent/task_graph.py` were
left alone. The four free preflight probes pass locally and 6/6 passed in the
deployed container.

### Decisions the human approved in words, 2026-08-29

Not drafts. `AGENTS.md`, Records, is the rule these are recorded under.

- A Modal volume for workspace persistence, and the sandbox kept only for
  untrusted content.
- A document is saved to the workspace and read with a tool, rather than
  extracted into the turn at admission.
- `view_pages` renders PDF pages with pypdfium2, not through the browser.
- A tool's media is delivered to the chat.
- The Firecrawl key is `WEB_FIRECRAWL_API_KEY`, under a `WebSettings` class with
  the `WEB_` prefix that does not exist yet. The human holds the key; it is in
  neither `.env` nor the Modal secret as far as this session knows.

### Open, and deliberately not done

- **Web access is not started.** It is the remaining sub-item, and it is what a
  person hits first: a link sent to the bot gets an honest refusal.
- **The sandbox is not started.** Rendering an arbitrary URL waits on it, because
  the worker holds `TELEGRAM_TOKEN`, `AGENT_DATABASE_URL` and `MODEL_API_KEY`.
- **`--no-install-recommends` was not used.** It would cut build time and image
  size further. Not taken because a missing recommend only shows up in a
  container, costing another slow deploy to discover; `/check` would catch it.
- **Nothing bounds how many pages reach the chat.** Two images per `view_pages`
  call, and a model reading a long scan would send a burst of photos. Not seen
  yet, not guarded.
- **Chainlit still refuses documents.** It admits uploads through
  `load_attachments`, which was not changed.
- **`app/agent/browser_verifier.py`** holds a second `find_chromium_browser` and
  its own launch flags, and never got the container flags. Reachable only from
  its own tests.
- The volume's `reload`/`commit` cost per turn is unmeasured, and two workers
  writing one person's directory has never been exercised. That is a narrower
  form of the serialization debt in queue 4.

## Checks

`pytest`: 537 passed, 1 skipped. Ruff clean on every changed file. Two
pre-existing lint findings in `ui/chainlit_app.py` and `app/agent/task_graph.py`
were left alone.

New dependency group `documents`: pypdf, python-docx, pypdfium2, pillow.
`reportlab` went into `dev`, only so the PDF tests build a file with a text
layer instead of skipping.

## Limitations

- Nothing is deployed, so `browser.inspect` is still unproven in a container and
  the volume has never been mounted. This is exactly the kind of claim the
  preflight module exists to stop being made.
- Chromium adds a few hundred megabytes to the worker's image. Its effect on the
  worker's 4.93 s cold start is unmeasured.
- A scanned document has never been through the real chain: the probes render a
  blank page, and the legibility check was a generated PDF read by me, not by
  Gemma.
- Chainlit still refuses documents: it admits uploads through `load_attachments`,
  the path-based function, which was not changed. Telegram is the product
  interface in both profiles, so this is an interface gap rather than a profile
  gap, but it is a gap.
- `app/agent/browser_verifier.py` holds a second copy of `find_chromium_browser`
  and its own launch flags, and did not get the container flags. It is reachable
  only from its own tests, and left alone rather than half-fixed.
