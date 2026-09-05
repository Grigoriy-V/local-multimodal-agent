# The scenario suite and the tools, reconsidered

**Date:** 2026-09-05
**Status:** analysis and a proposal for `ROADMAP.md` items 10, 11 and 12,
on the human's word of the same day. Nothing here is built. The evidence is
the day's runs on `assistant-llm-qwen-int4` (`reports/2026-09-05_qwen38_second_model.md`
§10–§13) and the human's own live run of the same request that scenario G
asks.

## 1. What the day showed

The same request, three outcomes: two scenario runs of G failed on the
model's route (a repeat loop the guard broke; a browser built by hand with
`npm` and `apt-get`, during which the model slept three times behind the
12 s idle window and paid three restores inside one turn), and the human's
live run of the same words passed in 75 s with `inspect_page` and four
`send_file`. At temperature 0 the route is a function of the exact input;
the inputs differed by a folder name, one line of the request, an empty
workspace against a full one, and ~110 tokens of brief.

The human's reading, which this report takes as the premise: the model is
not the variable to turn (thinking would raise a cost already 2.5x
Gemma's); the harness must make the route obvious, as the references do,
and the suite must measure outcomes, not routes.

## 2. The suite: what it is for, what it does

`scripts/loop_live.py` exists to check the loop and the tool boundary with
a real model — "the expectations are about the loop and the tool boundary,
never about the model's wording" — and `README.md` says "never on the
route the model took". What the checks actually assert, read one by one:

| Kind | Where | Verdict |
|---|---|---|
| A tool ran (`read_file ran`, `run_command ran`, `send_file ran`) | B, C, E, O, P, Q, R | outcome-shaped: the request cannot be met without it |
| An order of tools (`write_file then inspect_page`) | F, G | F's request names the tool, so F is legitimate; **G's is a route** — the request asks for a screenshot, not for a tool |
| What the model read (`[ref=e` in the inspect result, `chart.png` in a read) | F, R | outcome-shaped: the evidence reached the model |
| What was handed over (`sent` names end with `.html`, `.png`) | G | the outcome that matters |
| Loop properties (repeat guard, budget, fold, resume, stop) | D, E, J, K, Q | the suite's real subject |
| Counts (`at most five write_file`) | G | a proxy for a loop from 2026-09-03; keep only while ISS-0009's loop is open |

So the checks are mostly right and one is wrong: G demands the tool it
should only expect the effect of. F's `inspect_page` check becomes a
`view_web_page` check with item 12, and stays, because F's request says
"open it with" the tool.

The runner is where the suite fails its purpose:

1. **Its report is all-or-nothing.** Each scenario prints its block as it
   ends, but the deployed `scenarios` Function captures stdout and returns
   it when the batch returns, so the batch that died in H on 2026-09-05
   lost D's and G's summaries — the record had to be rebuilt from the
   store. What is printed should reach the log as it is printed
   (Modal streams stderr to the App log; `Turn.report` can write there
   too), and each scenario's verdict should be written to the deployed
   telemetry beside its run, so a crash loses nothing that already
   happened.
2. **A batch dies with its container.** The scenarios Function was lost
   once to Modal's CPU capacity ("waiting to be scheduled") and once to
   an unhandled error in one scenario; either way every scenario after
   it was never run and the ones before it were unreported. One
   scenario per Function call — `loop_live --deployed G` is already one
   call — and the local driver looping over letters would make each
   scenario its own input, reported when it ends, restartable by letter.
3. **The turn's timing carries the platform's.** A scenario's `seconds`
   includes the model's restore (A: 26.7 s of which 20 s the wake; H:
   40.8 s of which ~30) and, when a tool outlives the 12 s window, one
   restore per long tool inside the turn (G: three). The telemetry has
   the split (`first model token`, the tool timings); the report should
   show model time, tool time and wait time separately, so a number can
   be compared across days and models.
4. **The model sleeps inside a turn.** This is not the suite's defect
   but the product's, and the suite is where it shows: the person waits
   30–45 s in the middle of their own request whenever a command runs
   longer than 12 s. The general property — the model is not put to
   sleep while a turn is running — is item 6's adaptive window in its
   smallest form: the worker keeps the endpoint warm while a tool of the
   current turn runs, and nothing between turns. Belongs with item 6,
   named here because G measured it.
5. **What a scenario measures on the model's side is not a check.** G
   passing one run in three on Gemma and one in three on Qwen today is
   information about the model under this brief; a PASS/FAIL line hides
   the rate. The suite already prints run ids; a scenario that is known
   to vary should say so and be run more than once when it is the
   subject.

Proposed for item 10, in order: G's checks rewritten to outcomes (files
exist, files sent, screenshot sent, an answer, the guard's count kept
while ISS-0009 is open); per-scenario reporting to the log and the
telemetry; one scenario per deployed call with the local driver looping;
the report split into model, tool and wait time. The scenario texts stay.

## 3. The tools against the references

Hermes Agent's tools reference (`website/docs/reference/tools-reference.md`)
writes every description to one shape: what the tool does, what it
returns and in what format, when to use it instead of the shell, and
what artifact a person can be given. Read verbatim:

- `read_file`: "Read a text file with line numbers and pagination. Use
  this instead of cat/head/tail in terminal. Output format:
  'LINE_NUM|CONTENT'. … return a next_offset."
- `terminal`: "Execute shell commands on a Linux environment. Filesystem
  persists between calls. … Do NOT use cat/head/tail — use read_file. Do
  NOT use grep/rg/find — use search_files."
- `browser_vision` (the screenshot): "Take a screenshot of the current
  page so you can inspect it visually. … Includes a screenshot_path that
  you can share with the user by including MEDIA:<screenshot_path> in
  your response."
- `patch`: "Returns a unified diff."

DeepSeek Harness's reference gives a tool the same five parts — name,
description, input schema, the result contract, the side effects or
artifacts — and treats the result as a logged fact.

Ours, tool by tool, against that shape (what it does / what it returns /
what it leaves and where / when instead of the shell):

| Tool | Does | Returns | Leaves | Instead of the shell |
|---|---|---|---|---|
| `list_files` | yes | no ("list") | — | no |
| `read_file` | yes | yes (text, picture, pages) | — | no |
| `write_file` | yes | no | the file, implied | no |
| `edit_file` | yes | no | — | no |
| `run_command` | yes | yes (exit code, output) | **no**: where it runs, what persists, is in the brief and in the result, not here | inverted: says other tools are not shell commands, in the brief |
| `inspect_page` | yes | yes (structure, text, errors, "a screenshot for visual inspection") | **no**: the screenshot is a file at a path the model learns only from the result | — |
| `view_web_page` | yes | yes | **yes**: "the workspace path the screenshot was saved to … call send_file with the saved path" | — |
| `view_pages` | yes | yes | yes | — |
| `read_document` | yes | yes | — | — |
| `send_file` | yes | implied | — | — |
| `search_web`, `fetch_page` | yes | yes | — | — |
| `search_history`, `read_history` | yes | yes | — | — |
| `remember_fact`, `search_memory` | yes | partly | — | — |
| `set_goal`, `todo_write` | yes | no | — | — |

Two of these differences are the whole of G's failure. `inspect_page`
does not say that its screenshot is a file the person can be sent, so a
model asked for "a screenshot in the chat" goes looking for a way to
make one — a server, Chrome, puppeteer — while `view_web_page`, which
says exactly that, is named for the web. And `run_command` does not say
where it runs, what persists between calls or that the other tools are
not reached through it; the brief says some of it, three paragraphs away
from the schema the model reads at the moment of choosing.

The general property, item 11: **a tool's description is its contract —
what it does, what it returns and in what shape, what it leaves and where,
and what it is not for — and no tool exists without all of it.** The way
to make that a property rather than a habit is the way the Telegram label
became one: `Tool` gets `returns` and `leaves` beside `description`, the
schema the model sees is composed from the three (so a description cannot
omit them), and an offline test walks every toolbox and refuses a tool
with an empty `returns`, the same way
`test_every_tool_the_agent_can_call_has_a_readable_label` refuses one
without a label. The brief keeps only what is about the relation between
tools; what is about one tool moves into that tool.

## 4. One way to look at a page

Today two tools open a page in the same renderer: `view_web_page`
(address; rendered text, screenshot, its path, the console errors) and
`inspect_page` (workspace file; structure with refs, visible text,
console errors, screenshot, path in the result only). A model has to
know which name goes with its case, and the name that promises a
screenshot to send says "web".

Item 12: `view_web_page` takes a `page` that is an `http(s)` address or a
path in the workspace, and returns the same thing for either — structure
with a ref on every interactive element, the visible text, console errors,
the screenshot as an image and its workspace path, with the handover
sentence — and `inspect_page` goes. What goes with it: its definition in
`app/tools/browser.py`, its brief line and the "shell does not know
inspect_page" clause in `app/capabilities.py`, the mention in `send_file`'s
description, the Telegram label, `app/preflight.py`'s browser probe (which
calls it by name), the F and G checks, and thirteen test files that name
it (35 mentions). A local file is served to the page as it is now
(`serve_directory`, offline for anything but the workspace and public
addresses); nothing in the renderer changes, only the tool surface. No
new name: the human's word.

## 5. Order and gates

10, 11 and 12 are one change to how the model is told what it can do and
how that is measured; done together they are one offline test run and one
control-plane deploy, and then G, F and R on the deployed worker — three
scenarios, each a GPU turn, with permission at the time. 13 (the model
chosen from Telegram) needs its own design and comes after.

What this report asks the human to decide: the contract shape for item 11
(`returns` and `leaves` as fields composed into the schema, with the
test), the parameter name for the merged tool (`page`), and G's checks as
outcomes.
