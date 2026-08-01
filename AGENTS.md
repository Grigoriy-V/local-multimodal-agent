# Working Contract

## Primary principle

**Simplicity, speed, and the absence of bureaucracy or overengineering are the
main principle of this project.** If a process adds work without a concrete
safety, evidence, or user-value benefit, stop and propose a smaller alternative.

## Product positioning

This project is a **general local autonomous agent**, not a collection of demo
workflows or buttons that manually invoke individual tools.

- Natural-language conversation is the primary interface. In agent mode, one
  ordinary request enters one general harness that owns
  `understand -> plan -> act -> validate -> repair/finalize`.
- The agent chooses tools from the task and available evidence. Reading a file,
  opening a page, using a browser, capturing a screenshot and editing an
  artifact are agent capabilities, not separate user workflows.
- The UI may expose high-level intent and control such as conversational versus
  agent mode, working directory, grant approval, cancellation and status. It
  must not require buttons such as `preview`, `read_file` or `browser` to make
  the agent capable of doing its job.
- Plans define task-specific acceptance criteria and a validation strategy.
  Evaluation consumes real tool evidence. Production control flow must not
  contain a verifier hard-coded to Snake, one filename, one UI task or another
  benchmark scenario.
- Scenario-specific deterministic checks belong in tests and evaluations. A
  Snake task is one benchmark for the general harness, never the architecture
  of the product and never sufficient product acceptance by itself.
- Chainlit is a replaceable thin adapter. Agent behavior, tool choice, policy,
  persistence and evaluation remain UI-agnostic in `app/`.
- The workspace is the permission boundary, not a path-format restriction.
  Users may provide an absolute path that resolves inside the allowed workspace.
  A bare filename whose directory is unknown is ambiguous and must be clarified,
  not silently placed or searched in an invented directory.

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

A user-facing capability is complete only after a short end-to-end product
check of the actual experience. Technical presence is not product acceptance,
and a claim in the roadmap, decisions or reports must not be stronger than the
evidence that was collected.

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

Reviewed 2026-08-02. Update only for durable scope or safety changes.

- **Goal:** local multimodal agent over Gemma 4 12B IT with a model-agnostic
  architecture; see `docs/CONTRACT.md`.
- **Stage:** stages 1 through 3 and Version 1 are closed. Version 1.5 is open;
  its rejected benchmark-specific product surface has been disconnected while
  the general autonomous harness is designed; see `ROADMAP.md`.
- **Model access:** only through `ModelBackend`; the rest of the application
  must not import a provider SDK, tokenizer, or processor.
- **Persistence:** SQLite. Memory lives outside the model.
- **Out of scope:** fine-tuning, multi-agent orchestration, a vector database
  before SQLite retrieval works, Open WebUI as the main UI, business logic
  inside Chainlit callbacks, silent context truncation, unrestricted filesystem
  access, manual per-tool UI workflows as a substitute for agent autonomy,
  scenario-specific production verifiers, storing model-generated facts as
  trusted memory without an explicit save decision.

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
- Never expose a manual tool button as the only way for the agent to use that
  capability. Explicit approval controls permission, not tool selection.
- Never promote a benchmark-specific validator or scripted scenario into the
  production agent loop.

## Records

`ROADMAP.md` is canonical for current direction, state, order and the approved
step. `DECISIONS.md` records only decisions that change architecture or scope,
never work results. `docs/BACKLOG.md` is the source of truth for detailed
deferred and possible later direction. It is not a contract and does not
authorize work by itself; `ROADMAP.md` carries only its short active summary.

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
