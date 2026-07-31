# First-session handoff

Initializes the first project agent. A bootstrap snapshot, not a live status
source. After bootstrap, use `ROADMAP.md`, Git, and actual artifacts instead.

## Required first session

1. Read `AGENTS.md`, `ROADMAP.md`, `README.md`, and `docs/CONTRACT.md`.
2. Inspect the repository read-only and explain the current state and
   constraints.
3. Develop the implementation plan with the human.
4. When the plan is fixed, stop. A fixed plan does not authorize execution.
5. Wait for a separate, explicit command to implement.

During this session do not install dependencies, download weights, start the
model server, create or migrate a database, make an external call, or begin
implementation.

## Evidence to name before use

- model weights location and how the server is launched: not decided;
- credentials and endpoint configuration: not decided;
- test fixtures for image and audio input: not created;
- local constraints beyond `AGENTS.md`: none.
