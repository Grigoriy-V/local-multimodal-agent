# V2 item 4 — the assistant stops misdescribing itself, and the chat gets a shape

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** offline work complete. No deploy, no snapshot rebuild, no GPU,
no external action. Live product evidence is not collected and is the next gate.

## What was wrong

Two live defects from the step 2 acceptance session, neither of them a pipeline
failure:

- Asked in conversation to send a screenshot, the assistant answered that its
  output "supports only text", and repeated it when told otherwise. The adapter
  had been sending screenshots since the same session.
- The task result text said `browser.inspect` "is not available in this
  environment, I cannot provide a screenshot" — in a message whose own
  acceptance criteria included "a screenshot is provided: evidence from
  `inspect_page` … a rendered image is visible in the tool output". Two false
  statements at once: a tool name that has never existed (it is a *capability*
  name), and a denial of evidence the same message counted as passing.

The cause is the same in both: everything the model knew about itself was prose
someone typed. The system prompt listed tool names by hand and said nothing at
all about what reaches the user, and the implementer prompt let the model speak
for a delivery path it cannot see.

## What was built

### A capability description that is read, not written

`app/capabilities.py` generates it from three sources that cannot go stale
independently of the thing they describe:

- the `Toolbox` the graph is actually compiled with, including tools added
  outside the registry, so a narrower grant produces a narrower description;
- `app/attachments.py`, the authoritative admission policy, for what can arrive;
- a `Delivery` the interface declares, for what can leave.

`Delivery` exists because only an adapter knows. The same answer with the same
picture in it reaches a Telegram user as a photo, a Chainlit user as an inline
element, and a caller with no rendering as nothing; the model cannot find that
out. Both adapters declare it next to the method that does the rendering, so the
declaration and the code it describes are edited together.

The brief is deliberately short. Tool schemas already carry names, parameters
and descriptions on every request; the brief adds only what a schema cannot say
— that the list is exhaustive, what may arrive, what may leave, and which calls
wait for a yes.

`tool_inventory` — the sentence that closes the list — now also goes to the task
implementer and the task validator, derived from each one's own toolbox. Those
two get narrower toolboxes than the conversation does, which is exactly the
situation that produced the invented name.

The hand-written guidance stays. "Use `write_file` to create or fully replace a
file and `edit_file` to replace one exact unique fragment" is behaviour worth
keeping in words, not inventory. What it cannot do any more is outlive its
tools: a test asserts that the snake_case words in `DEFAULT_SYSTEM_PROMPT` are
exactly the tool names that exist.

### A check a person can run

`/can` in Telegram prints what the agent can see, hear, receive, send, run and
change, plus its workspace root — from the same derivation, with no model call
and therefore no GPU. It is what the assistant's claims about itself are
measured against, and it costs nothing to ask.

### Telegram presentation

`Formatted` carries an HTML rendering and the plain text it degrades to. Only
this project's own headings become tags; every body is escaped, model output
included. A message that no longer fits in one piece is sent as plain text
instead, because `split_message` cuts on length and a cut `<b>` makes Telegram
refuse the whole message. That keeps the module's existing rule — never mark up
model text — intact.

Applied to the plan a person approves, and to the finished task, which now leads
with the result, then the checks (`✓`/`✗` with their detail), then the files,
then the counts. A batch of tool calls arrives as one message rather than a
burst of near-empty ones.

The store still holds the harness's canonical result text; the shaping is the
adapter's, which is where presentation belongs.

### The approval pause

`deploy/modal/autoscale.py` now warns below 20 s, with the reason: at 10 s one
approval became two cold starts, because the container scaled to zero while the
plan was being read. It warns rather than refuses — a short window is right for
a throughput measurement, and roadmap item 5 plans an adaptive one — but it is
never right by accident.

## Checks

- `uv run python -m pytest -q` — **439 passed** (418 before this work);
- `ruff check` on every changed file — passed; the pre-existing `E402` block in
  `ui/chainlit_app.py` and `F401` in `app/agent/task_graph.py` are unchanged and
  untouched;
- `git diff --check` — passed;
- the assembled system prompt was printed and read end to end.

New tests worth naming, because each one is a defect that already happened:

| Test | What it prevents |
|---|---|
| `test_the_model_is_sent_the_derived_brief_every_turn` | the description existing but never reaching the model |
| `test_a_narrower_grant_produces_a_narrower_brief` | describing a tool the agent was not given |
| `test_the_default_prompt_names_only_tools_that_exist` | the hand-written prompt outliving a tool |
| `test_an_interface_that_cannot_show_media_says_that_instead` | telling a text-only caller that pictures arrive |
| `test_the_implementer_is_told_which_tools_it_actually_has` | the `browser.inspect` claim |
| `test_a_formatted_message_too_long_to_send_whole_arrives_plain` | a cut tag losing an entire answer |
| `test_can_is_answered_from_the_wiring_and_never_by_the_model` | the honest check becoming another model claim |

## Cost and state

Zero. No container started, no request sent to the endpoint, nothing deployed.
The GPU was not woken at any point during this work.

## Not done

- **Live product evidence.** Nothing here is confirmed against the real
  assistant: that it now answers a capability question correctly, that `/can`
  agrees with it, and that the shaped plan and result read well in a real chat.
  That needs one warm window and is a human gate.
- **Agentness evidence** — the fourth part of roadmap item 4: multi-step work
  that survives a restart, asks when it should, and claims no result it did not
  verify. Also live work.
- Telegram voice recognition quality, still deferred as separate work.
