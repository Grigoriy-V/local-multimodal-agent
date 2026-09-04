# Version 2 — 4.9 saying only what was observed, against the references

**Date:** 2026-09-04
**Agent:** Claude, direct session
**Status:** analysis. No code changed, nothing started. Every design below is
an option until the human approves it in words; the recommended shape is
marked and is not yet approved. The same day 4.8 (`ask_user`) was moved to
Not started on the human's word: a feature, not architecture.

## 1. What 4.9 is about

`ROADMAP.md` 4.9: "the assistant describes artifacts and sources it did not
open … three rounds of prompt wording settled nothing … the scenario suite is
the only way to accept a change in what the model does. Includes the residual
acceptance 4.3 did not demonstrate" — proportional validation: a thing made is
looked at before it is described.

The defects it owns, all model behaviour, all still open:

| | What was seen | Where |
|---|---|---|
| ISS-0004 | a page described from its address alone, no `fetch_page` (run `45f78d7e`); a file reported that was never created; `castle` reports glowing windows with no look | 2026-08-30, 09-03 |
| ISS-0028 | "I checked my memory, nothing is saved" — no `search_memory` call, facts present | 09-03 |
| ISS-0010 | "here is the screenshot" after `inspect_page`, nothing sent; then "I cannot attach an image" | 09-03, twice |
| ISS-0003 | files handed over as paths or a markdown image; on 09-04 the files *were* sent and the wording still carried `![…](…png)` | 08-30 … 09-04 |
| ISS-0008 | an application described as working that was never opened; "проверь что всё работает" produced no look | 08-31, 09-03 |

One family: **a claim in the answer that the turn's own record contradicts** —
a source not opened, a check not run, a delivery not made, a look not taken.

## 2. What has been tried, and what it showed

- **Wording, three rounds** (`reports/2026-08-30_v2_prompt_assembly.md`):
  better and worse in turn; `broken_page` showed that steering the model to
  `inspect_page` made one answer *worse*, because looking is not a superset
  of reading. The capability brief since 2026-09-03 says where the person
  is, that a path delivers nothing, and every tool that leaves a file names
  the `send_file` call in its result. The screenshot now goes unprompted
  most of the time; the markdown image still appears beside it.
- **The steering seam** (4.3, `app/agent/stopping.py`): an extension may
  refuse an ending once with a structured instruction; the default stops.
  Its only user, `FinishesItsOwnList`, is at limit 0 since 2026-09-03
  because every objection bought a tick and a duplicate answer — the plan
  was not evidence the model lacked.
- **The instruments**: `tools/prompt_scenarios.py` (same requests, two
  variants, what the agent *did*) and `scripts/loop_live.py` A–K (PASS/FAIL
  on events and outcomes). G already asserts "no path was offered as
  delivery" and failed it once on 2026-09-04.

## 3. What the references do

Read 2026-09-04: Claude Code's hooks reference (`Stop`), Anthropic's
"Effective harnesses for long-running agents", OpenClaw's tracker on the
same defect (#40069 "claims to execute but no actual calls made", #5073
"claims to write memory files without performing the operations"), the
AgentLTL paper on trace constraints, DeepSeek Harness' evidence plugins.

| Concern | Reference shape | Ours today |
|---|---|---|
| The defect itself | OpenClaw has it verbatim — claimed reads, writes, posts with no call; the community fix is a SOUL.md rule "never report a task as complete without verification evidence". Anthropic's own long-running agents "would fail to recognize that the feature didn't work end-to-end". | ISS-0004/0028/0010/0003/0008 |
| Where the harness gets a say | Claude Code `Stop` hook: fires when Claude finishes, receives `last_assistant_message` and the transcript, may answer `block` with a reason; "Claude sees the blocking reason and can continue working"; a loop guard keeps it from firing on the immediate next stop. Documented use: "verifying work before the agent stops". | `TurnStopping`: the same seam, `Candidate` carries the turn's messages and the count of objections; limit per turn |
| What the check is made of | Anthropic: structural accountability — a `passes` field the agent may change only by testing, "it is unacceptable to remove or edit tests"; give the agent the tool that sees the end-to-end result. AgentLTL: grounding as a trace constraint, every entity in the final answer must appear in prior tool outputs. | The trace already knows every call, result, outbound part and written file of the turn |
| A judge model | DeepSeek's research plugins bind claims to evidence snapshots with a verdict per claim — for reports, not chat. Nobody runs a second model on every turn of an assistant. | Rejected in 4.3, stands |
| Wording | Everyone has the rule in the prompt; nobody reports it sufficient. | Three rounds, not sufficient |

The reading: the references that got anywhere did it by giving the harness a
**structural veto grounded in facts it holds**, not by a better sentence and
not by a second model. Our seam is that veto, unused.

## 4. What the harness knows without reading the answer

Facts of one turn, all in `Candidate.messages` and the tool results:

1. the URLs in the person's message, and which of them a `fetch_page` /
   `view_web_page` call opened;
2. the files `write_file` / `edit_file` produced, their kind, and whether
   `inspect_page` (HTML) or `read_file` (else) looked at them afterwards;
3. the workspace items sent this turn (`outbound` parts) — and, one
   syntactic step into the answer, a markdown image or a path of a file
   that exists and was not sent;
4. whether any tool ran at all.

What it does not know: whether "I checked my memory" is a claim (ISS-0028),
whether "here is the screenshot" refers to a send (ISS-0010), whether an
application works. Those need a reader, and a reader is the judge nobody
runs.

## 5. Options

- **A — Objections from facts, once per turn (recommended).** One
  `TurnStopping`, `SaysWhatItSaw`, composed with the todo one, sharing the
  per-turn objection count with a limit of one. Three checks, first one
  wins, each with a way out that is not a tool:
  - *an address not opened*: the message carries a URL and no fetch/view
    call of this turn opened it — "open it, or say plainly that you did not
    read it";
  - *a thing made and not looked at*: an HTML file was written or edited
    this turn and no `inspect_page` followed — "look at it before you
    describe it, or say that you did not look" (the residual 4.3
    acceptance, in its narrowest form: HTML only, because that is what
    `inspect_page` can see and what ISS-0008 is about);
  - *a path offered as delivery*: the answer names a workspace file that
    exists or carries a markdown image, and nothing was sent this turn —
    "send it with send_file, or leave the path out; a path reaches them as
    text". Syntactic, the same check G runs.
  No check chooses a tool for the model, none ends the turn, none reads
  meaning; each is "the record says you did not, so either do or say so".
  Cost: one more step on the turns that trip it, roughly 5–15 s; bounded
  at one objection a turn.
- **B — A judge call at the ending.** Rejected in 4.3 and by every
  reference: a model call on every turn, and a semantic judgement moved out
  of the agent.
- **C — Grounding as a hard constraint** (AgentLTL): refuse any answer
  naming an entity absent from tool outputs. Research-grade, and wrong for
  a chat assistant that may answer from what it knows.
- **D — More wording.** Three rounds say no; the brief keeps its lines and
  they are measured beside A, not instead of it.
- **E — A `finish` tool with fields.** Rejected in 4.3, stands.

What A leaves to the model, stated plainly: ISS-0028 and the wording half
of ISS-0010. They are measured, not fixed, here.

## 6. Acceptance: the suite is the instrument

- **Offline**, `tests/test_says_what_it_saw.py`: each check fires on its
  fact and stays silent when the tool ran; one objection per turn even when
  two facts hold; the way-out sentence accepted (the model says "I did not
  open it" and the turn ends); composed with the todo extension.
- **Live**, `scripts/loop_live.py`: **L** a pasted URL — PASS when the turn
  either fetched the page or the trace shows one steering and the answer
  ended after it; **M** `castle` — a page written and, after the objection
  if needed, looked at (`inspect_page` in the turn); **N** "make X and hand
  it over" — a file sent, and no path or markdown image left in the answer
  (the G check). Asserted on tools, outbound parts and `turn_steered`
  events; never on wording.
- **Attribution**, `tools/prompt_scenarios.py --label before/after` on
  `castle`, `broken_page`, `web`, `note`: the same requests with the
  extension off and on, model calls and tool order side by side, the
  answers read by a person. One warm window, one permission.
- **Then the person's own session**, as with every step.

## 7. Size, cost, gates

`app/agent/observed.py` (~120 lines: the three facts, the three sentences,
the `TurnStopping`), composition in `create_agent` beside
`FinishesItsOwnList`, `turn_steered` already traced. Tests ~150 lines; L, M,
N ~80. No schema, no migration, no deploy of the model app. Gates: the live
run (GPU), the deploy, the after-deploy run.

## 8. What this document does not authorize

No implementation, no deploy, no GPU run. The next gate is the human's word
on §5 A and the acceptance in §6, then a separate start signal.

## 9. Withdrawn, 2026-09-04, on the human's word

The human read §5 A and named it: checks 1 and 2 are past bugs rewritten as
a script — "wrote HTML and did not run the browser" is the model's choice of
how to work, hard-coded, which the primary principle forbids; and no
reference ships such a rule (Claude Code ships the `Stop` seam, the checks
are each project's own). Check 3 as an adapter rule was left in doubt and
called overkill for now. **Option A is withdrawn; 4.9 stays measurement.**
The human's rule is now in `AGENTS.md`, Primary principle.

Asked whether two of the five are the harness's after all, the record says:

- **"I checked my memory, nothing is saved"** (ISS-0028) — partly the
  harness's. Facts reach the model only through the per-turn retrieval,
  which is a keyword match of the *latest user text* against the facts
  (`latest_text` → `store.search`), and when nothing matches the layer is
  simply absent — no line says a search ran and found nothing, and the
  brief never says facts arrive this way. "Что ты помнишь" and "да" match
  no fact by keyword, so the model was looking at a context with no facts
  and no sign why. It still had `search_memory` and chose a sentence over
  the call, but the harness handed it the reason for that sentence. The
  general property this violates: what the model is told about its memory
  should be true of the memory, not of one keyword query. Fixing it is a
  design question about retrieval (what the automatic layer is for beside
  the tool, and what it says when it finds nothing), not a check on the
  answer.
- **"Here is the screenshot", nothing sent** (ISS-0010) — the model sees
  the screenshot itself (`inspect_page` returns the image to it), so from
  where it sits the picture *is* in the conversation. The brief has said
  since 2026-09-03 that observation tools keep their evidence between the
  model and the tool, and the tool result names the `send_file` call. Both
  runs of ISS-0010 (04:06Z) predate that second mitigation; since it,
  runs `7673ce55` and the 2026-09-04 after-deploy G sent the screenshot
  unprompted. Not seen since; to be closed on evidence, not built on.

Which of the family predate the tool system (4.5, 2026-09-03) and are still
current: the page described from its address alone — seen again on the tool
system (run `45f78d7e`), current. A file handed over as a path — seen again
2026-09-04 with the send made and a markdown image beside it, current in
that reduced form. An application called working without a look — seen
again on the tool system ("Task Board test 3"), current; its named cause,
that nothing can exercise a page, is a capability gap (browser actions exist
since 2026-09-03 and are not exposed to the model), not a check. The
screenshot claim — not seen since the tool result names the send. The
memory claim — on the tool system, and partly the harness's, above.
