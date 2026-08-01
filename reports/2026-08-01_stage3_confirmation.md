# Stage 3, first step — checkpoints, resumable turns, confirmation

**Date:** 2026-08-01
**Model:** `gemma-4-12b-it` (w4a16 QAT) on vLLM 0.26, `http://127.0.0.1:8000/v1`
**Code:** `app/agent/graph.py`, `app/agent/runtime.py`, `app/tools/`, `ui/`

## What was built

The graph keeps its four nodes. What changed is that it can now stop, ask, and
be picked up again later — including by a different process.

| Piece | Where |
|---|---|
| `write_file`, the first destructive tool | `app/tools/filesystem.py` |
| `Tool.destructive`, `Toolbox.destructive(name)` | `app/tools/base.py` |
| One `interrupt` per batch, before any tool runs | `app/agent/graph.py` |
| Turn boundary in the state reducer | `app/agent/graph.py` |
| `AsyncSqliteSaver`, `Agent.pending`, `Agent.resume` | `app/agent/runtime.py` |
| The approve/decline prompt and the pick-up on start | `ui/chainlit_app.py` |

Four things were decided while building it.

**The question is asked before any tool in the batch runs.** Resuming restarts
the node from the top, so a tool that had already run would run a second time.
One `interrupt` carrying every risky call in the batch is the only shape where
that cannot happen.

**A turn ends at the next user message.** With a checkpointer the state outlives
the turn, so the reducer needs to know where one stops — otherwise the next turn
inherits the last one's messages and stores and sends them twice. No node
produces a user message, so a user message can only mean a turn is beginning.

**Without a checkpointer a destructive call is declined, not run.** `interrupt`
needs somewhere to wait. If there is nowhere, the safe reading of "ask first" is
that the answer is no.

**Checkpoints live in their own file.** `data/checkpoints.sqlite3` next to
`data/memory.sqlite3`. The conversation is the durable record and is ours;
a checkpoint is in-flight state in LangGraph's schema, and deleting the file
costs nothing but the ability to finish an interrupted turn.

A fifth change was forced by the checkpoint: `Message.__post_init__` now
normalizes `content` and `tool_calls` to tuples. Msgpack gives lists back, so
without it a message read out of a checkpoint was not equal to the one put in.
LangGraph is also given an explicit allowlist of the four types it may
reconstruct, rather than being left to deserialize anything.

## Live evidence

`.venv\Scripts\python.exe -m scripts.stage3_live`, one run, a temporary
workspace, the real graph and the real model.

| Step | What happened |
|---|---|
| "Rewrite notes.txt so it says 43." | model called `list_files`, then `read_file`, then `write_file` |
| At `write_file` | the turn stopped; `pending` returned the call; the file still read `the answer is 42` |
| Agent closed, a new one opened | `pending` returned the same call, id and arguments intact |
| Approved | `overwrote notes.txt (2 characters)`; the model then said it had updated the file |
| "…so it says 44." then declined | file unchanged; the model answered "you declined the request to update `notes.txt`" |
| The store afterwards | all twelve messages of both turns, in order, each once |

Whole flow: **4.0 s**.

## Closing criteria for this step

| Criterion | Evidence |
|---|---|
| A destructive tool cannot run unasked | live run; `test_a_write_stops_the_turn_and_asks`, `test_without_checkpoints_a_write_is_refused_rather_than_run` |
| A question outlives the process | live run across a close/reopen; `test_a_pending_question_survives_a_restart` |
| Declining is an answer the model can act on | live run; `test_declining_leaves_the_file_alone_and_tells_the_model` |
| The checkpoint does not leak one turn into the next | `test_a_second_turn_starts_from_an_empty_state`, `test_the_whole_turn_is_stored_once_it_finishes` |
| Nothing below the graph was rewritten | the store, the context layers and `ModelBackend` are untouched |

156 offline tests pass, up from 137.

## Limitations

- Only `write_file` is destructive, so confirmation has exactly one subject.
  Deleting and moving files do not exist yet.
- The confirmation is per call, not per turn: three writes in one batch are
  three questions.
- Checkpoints are never pruned. A long-lived thread accumulates them, and
  nothing removes a checkpoint once its turn has finished.
- A turn that stopped to ask is only picked up for the thread the UI resumes,
  which is still the most recent one — there is no list of threads waiting on an
  answer.
- Approving is still a click in Chainlit. Nothing carries the decision to
  another consumer, because there is no other consumer yet.
