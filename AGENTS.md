# Working Contract

## Primary principle

**Simplicity, speed, and the absence of bureaucracy or overengineering are the
main principle of this project.** If a process adds work without a concrete
safety, evidence, or user-value benefit, stop and propose a smaller alternative.

## Execution

Work directly as one project agent. Do not delegate or create subagents. The
human controls direction. Discussion, planning, and roadmap edits do not
authorize implementation.

Work on one approved step at a time. Within it, own:

`inspect -> implement -> test -> diagnose -> fix -> record -> report`

Routine implementation choices, debugging, proportional tests, and correction of
your own changes need no approval. Return once with a complete result or one
consolidated blocker. Run checks in proportion to concrete risk; documentation
edits that do not touch code, config, commands, or safety need no test run.

This repository is run from more than one agent application. Do not assume which
one is active and do not rely on features specific to one of them. Only one
application works in the repository at a time.

## Context to read

| When | What |
|---|---|
| Always | `AGENTS.md`, `ROADMAP.md` |
| Only when the task names it | `docs/AGENT_PROTOCOL.md`, `docs/CONTRACT.md`, `reports/*`, `DECISIONS.md` |
| Never automatically | `docs/BACKLOG.md`, the JSONL journals, Git history |

Do not assume a useful file will be discovered. Mandatory information belongs in
this file, in the task, or in a file the task explicitly names.

## Project boundary

Reviewed 2026-08-01. Update only for durable scope or safety changes.

- **Goal:** local multimodal agent over Gemma 4 12B IT with a model-agnostic
  architecture; see `docs/CONTRACT.md`.
- **Stage:** 3 of 3, under way. Stages 1 and 2 are closed.
- **Model access:** only through `ModelBackend`; the rest of the application
  must not import a provider SDK, tokenizer, or processor.
- **Persistence:** SQLite. Memory lives outside the model.
- **Out of scope:** fine-tuning, multi-agent orchestration, a vector database
  before SQLite retrieval works, Open WebUI as the main UI, business logic
  inside Chainlit callbacks, silent context truncation, unrestricted filesystem
  access, storing model-generated facts as trusted memory without an explicit
  save decision.

## Gates

| Action | Who |
|---|---|
| Read, implement, refactor, write tests | agent |
| Offline tests and short local checks | agent |
| Requests against an already running model endpoint | agent |
| Starting or stopping the vLLM server | agent, once the human has permitted it |
| Downloading model weights | human |
| Materially expensive or long GPU work | human |
| Deleting or migrating a populated database | human |
| Git remote, push, publication, deployment | human |
| Anything destructive or externally mutating | human |

Before a human-run command, report what it does, expected duration, VRAM cost,
and the exact command. Never expand scope to another repository.

## Hard rules

- Never add a `Co-Authored-By` trailer or tool-attribution line to a commit.
- Never put secrets, credentials, or private personal material in the
  repository, in evidence, or in the journals.
- Never overwrite unrelated user changes.
- Never silently change a configuration that produced a recorded result; a
  changed configuration gets a new identity.
- Never grant a model tool unrestricted filesystem access; every path-taking
  tool validates against an explicit allowed root.
- Never let a tool marked destructive run without an explicit answer from the
  user; where there is nowhere to ask, the answer is no.
- Never send the full conversation history on every model request.

## Records

`ROADMAP.md` is canonical for direction and holds the plan, current state, and
the approved step. `DECISIONS.md` records only decisions that change
architecture or scope, never work results. `docs/BACKLOG.md` holds ideas and has
no authority.

Use `tools/work_log.py` rather than hand-editing the JSONL journals; see
`--help`. Set `--agent` to the application actually running, so records stay
comparable across applications.

- `reports/agent_tasks.jsonl`: one final record per material task.
- `reports/ml_work.jsonl`: one record per measured outcome — latency, VRAM,
  tool-call success, memory retrieval quality, cost.

Do not log routine reads or minor documentation edits. Keep commands, metrics,
and long analysis in `reports/`, not in `ROADMAP.md`.

The final response states: changed files, checks run, measured results,
external actions and their cost, limitations, and the next human gate.
