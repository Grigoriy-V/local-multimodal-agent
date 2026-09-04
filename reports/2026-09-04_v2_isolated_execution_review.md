# Version 2 — 5 isolated execution, against the references

**Date:** 2026-09-04
**Agent:** Claude, direct session
**Status:** analysis, and a shape **approved by the human on 2026-09-04**
(§5) after four rounds in the chat. Step 5 was selected the same day and
split on their word into the deployed profile (5a, Modal) and the local one
(5b). Nothing is built; implementation is a separate start signal.

## 1. What step 5 is

`ROADMAP.md` 5: an execution backend behind the 4.2 seam — shell, Python and
package installation in a workspace holding no control-plane secret.
Isolation, not a confirmation prompt, is the boundary for arbitrary
generated code. `DECISIONS.md` 2026-08-30: once a run is authorized, commands
inside the boundary do not ask one by one; `DECISIONS.md` 2026-08-30 (4.3):
the natural-request PDF scenario returns as this step's acceptance.

What the product gets: the assistant can *run* what it writes — tests, a
script, a converter, a server — and see the result, which is the structural
answer to "an application called working without a look" (ISSUES, seen
2026-08-31 and 09-03) for anything that is code. Today it can only write and
render.

## 2. What exists

- **The seam.** `ToolExecutor` (`app/tools/execution.py`): `pre_execute ->
  execute -> post_execute`, the executor owning the timeout, the 32k output
  bound with head and tail, the failure codes, the model projection. A new
  tool gets all of it by being a `Tool`; a new *place to run* is a `Tool`
  whose body talks to a runner.
- **The workspace.** One directory per person (`user_workspace`), the root
  every path-taking tool validates against. Local: a Windows path under the
  repository (`AgentSettings.workspace`). Deployed: `/workspaces/<scope>` on
  the `assistant-workspaces` Volume, reloaded before a turn and committed
  after it (`deploy/modal/control_app.py`).
- **The secrets.** Deployed, the worker function carries `control_secret`
  (Telegram token, model key, database URL) in its environment. Anything
  that runs *in* the worker inherits it unless scrubbed; anything that runs
  elsewhere never sees it. The renderer already follows the second pattern:
  same image, no secret, no volume.
- **The brief.** `capability_brief` states once what the environment can do;
  "whether isolated execution exists" is named there as a fact to add.
- **The gates.** A product-runtime worker start is a human gate during
  development, every time (`AGENTS.md`). In the product the person's request
  to the assistant is the authorization; this step must not confuse the two.

## 3. What the references do

Read 2026-09-04: Claude Code's sandboxing reference, Codex CLI's sandboxing
and Windows-sandbox pages, Modal's Sandbox guide, reference and pricing,
OpenClaw's gateway sandboxing, Hermes' execution environments.

| Concern | Reference shape | Notes for us |
|---|---|---|
| The boundary on a developer machine | **Claude Code**: the OS enforces it — Seatbelt on macOS, `bubblewrap` + `socat` on Linux and WSL2, native Windows unsupported. Writes allowed in the working directory, the session temp dir and added dirs; network through a proxy with a domain allowlist, first new domain prompts. A command the sandbox blocks fails with the path or host named, and the model may retry unsandboxed through the normal permission flow. **Codex**: the same primitives (Seatbelt; bubblewrap on Linux/WSL2; a native Windows sandbox with a low-privilege user and ACLs), modes `read-only` / `workspace-write` (default) / `danger-full-access`, network blocked by default, escalation to the person when a command hits the boundary. | The human's sense "a folder with full access" is what it feels like from inside: full inside the folder, the fence invisible until touched. Neither reference is a container. Both fall back to running without isolation when the primitives are missing, and say so. |
| The boundary in a hosted product | **OpenClaw**: Docker, scope `session` / `agent` / `shared`, workspace mounted `rw` / `ro` / hidden, network `none` by default ("package installs will fail"), `setupCommand` once per container, idle pruning, an explicit `elevated` escape to the host for authorized senders. **Hermes**: one `terminal` tool over local, Docker, SSH, Modal, Daytona, Vercel; environments cached by task id for reuse; local backend is the host shell with an env blocklist and nothing else. **Modal Sandbox**: gVisor container, `Sandbox.create(image, volumes, secrets, workdir, timeout ≤ 24 h, idle_timeout, block_network / outbound allowlist, cpu, memory, name)`, `exec` returning a process with streams, `from_name` / `from_id` to reattach from another process, filesystem snapshot to an Image (30-day TTL), memory snapshots experimental. Billed at ~3× a Function: $0.0000394 per core-second and $0.0000067 per GiB-second, about $0.12 per hour for 1 CPU and 2 GiB while alive. | A container per *session*, looked up by name, with an idle timeout, is the shape every hosted reference converges on. Nobody starts one per command. |
| The tool the model sees | Hermes: one `terminal` tool, a fresh `bash -c` per command, cwd and env carried between commands, 180 s default timeout, background tasks keep the environment alive. OpenClaw: `exec` plus `process` for long-running ones. Claude Code and Codex: one shell tool, background runs as a later addition. | One tool, not a Python tool and a pip tool and a shell tool. Python and `pip` are commands. |
| What runs inside vs outside | OpenClaw: file tools *also* move into the container when sandboxed, so the model's read and the command's write agree. Hermes: same — the environment owns the filesystem. | Our file tools run in the worker against the same directory the sandbox mounts. That is fine only if both see the same files at the same moment: §5a. |
| Network | Codex and OpenClaw: off by default. Claude Code: allowlisted domains through a proxy. | The value of this step for a person is largely `pip install` and `npm install`. With no secret inside, what egress can leak is the person's own workspace, which the model can already read and the browser can already fetch against. |

The reading: the references agree on the shape — one shell tool, a per-session
environment that persists between commands, an OS or container boundary
around the workspace, no secret inside, and an honest fallback when the
boundary cannot be made. They differ on network, and that is a product
choice, not a security fact.

## 4. The questions the step has to answer

1. **What the boundary is, per profile.** Deployed: the worker's own process
   with the secret scrubbed (no fence around the volume or the network), a
   separate Modal Function without secrets (cold per command, nothing
   installed survives a call), or a Modal Sandbox (a container per session,
   reattachable, nothing installed lost until idle). Local: the Windows host
   process (no primitive to fence it), WSL2 with `bubblewrap` around the
   workspace (the Claude Code and Codex boundary), or Docker.
2. **Lifetime.** Per command, per turn, or per person's session; and what
   "idle" means when a person is writing the next message.
3. **One filesystem.** The worker's file tools and the sandbox's commands
   must see one directory, or the model writes a file and the command does
   not find it.
4. **Network.** On, off, or allowlisted.
5. **What the model is told**, and what a blocked or timed-out command
   reports back.

## 5. The shape — approved 2026-09-04

Reached in the chat with the human on 2026-09-04 in four rounds, each of
which changed the answer; recorded here as approved, with the rounds kept so
the next session sees why the earlier §3 reading was not enough.

**Round one** proposed the references' boundary as read: a Modal Sandbox
deployed, WSL2 with `bubblewrap` locally. The human: neither Claude Code nor
Codex installs WSL on Windows, and inside one folder with full access a
fence does nothing. True — Claude Code on native Windows has no sandbox at
all and says so; the fence is about what is *outside* the folder, and on a
developer's own machine that job is done by the person. **Round two**, with
the old wording ("isolation, not a confirmation prompt") set aside as
written before the tool system: what the product needs is an environment
that lives through a session; isolation is second and, on the human's
machine, absent in every reference. **Round three**, the human's five
points: idle three minutes, cold start measured, no boundary the agent has
to understand, two modes with full access the default, base tools in the
image. **Round four**, the human unsure about a Sandbox that loses what
was installed: what is installed lives in the workspace on the Volume,
where nothing loses it; what a container buys is secrets outside, a
crashed command not killing the worker, and background processes — and a
Function without secrets, the renderer's own pattern, buys the first two
at a third of the price and with no new primitive.

### What is decided

- **Where a command runs, deployed:** a Modal Function `run_command`
  beside the renderer, built from the same image plus the tools below, the
  `assistant-workspaces` Volume mounted, **no secret**, `scaledown_window`
  180 s, timeout the executor's. Nothing installed into the container
  survives it, by design; nothing needs to.
- **Where a command runs, locally:** a process on this machine, `cwd` the
  workspace, the environment reduced to `PATH` and what a shell needs, no
  `.env` value in it. No WSL, no `bubblewrap`, no Docker. Claude Code on
  the same machine runs the same way.
- **What survives:** whatever is in the workspace. `HOME` is set inside the
  workspace for commands, a venv there is the way to install Python
  packages, `node_modules` land there on their own. The brief says so in
  one sentence: the environment between turns may be fresh, install into
  the workspace. The first command in a fresh container says "new
  environment" in its result, so a missing package is not a surprise.
- **Network:** on. Installing is the point; no secret is inside; what
  could leave is the person's own workspace, which the model reads anyway.
- **The tool:** one, `run_command(command, timeout_seconds=120)`, not
  `replay_safe`. A fresh shell per command in the workspace; the result is
  the exit code, the bounded output (the executor's head and tail), the
  elapsed time. A timeout kills the process tree and reports `timeout`.
  Python, `pip`, `node`, `git` are commands, not tools. Background
  processes are v2 (they are what a Sandbox would be for).
- **Two modes, per conversation:** `full` — everything inside the
  workspace runs without a question, the default in both profiles — and
  `careful`, where tools that change the workspace (`write_file`,
  `edit_file`, delete, `run_command`) ask first through the existing
  approval path. Claude Code's permission modes, generalized: a tool gains
  a `mutates` flag, the toolbox's `requires_approval` reads the mode, a
  chat command switches it. Third-party and infrastructure effects stay
  gated in both modes as before.
- **Base tools in the image:** python3 + pip + venv, node + npm, git, curl,
  zip/unzip, tar, jq, ffmpeg, imagemagick, poppler-utils, pandoc. Not
  LibreOffice, for its size. Locally, what the machine has; the brief
  lists what is found.
- **For the agent there is no boundary to understand.** Commands run in
  its workspace, on the same files its other tools see. Deployed, the
  Volume is reloaded before and committed after each command as the
  worker already does per turn — and the first live line checks the
  round trip: a file written by a command read by `read_file` in the same
  turn, and one written by `write_file` seen by the next command.

### What was set aside, and why

- **Modal Sandbox** — v2, when a background process (a dev server the
  browser then looks at) or a filesystem snapshot is worth its price. A
  second implementation of the same runner; nothing in v1 is shaped
  against it.
- **WSL2 + bubblewrap locally** — the references' boundary on Linux, not
  what the human's daily tools do on this Windows machine; the person is
  the boundary there, as in Claude Code.
- **Running in the worker** — loses everything in 60 s anyway, and a child
  of the worker reads the worker's secrets through `/proc` whatever its
  environment says. With a Telegram token and the database URL at stake,
  and the alternative costing cents, this is not where to save.
- **"Isolation, not a confirmation prompt, is the boundary"** as a
  universal — kept for the deployed profile, where nobody can be asked,
  and there the boundary exists for persistence and secrets anyway;
  replaced locally and in the modes by Claude Code's rule.

## 6. Acceptance: the suite is the instrument

Offline (`tests/test_run_command.py`): a fake runner through the executor —
exit code and output projected, a timeout reported with the code, output
over the bound cut with head and tail; the modes: `careful` asks for a
mutating tool and `full` does not, the gated set unchanged in both; the
local runner on a real `python -c` and a real timeout on this machine.

Live, local (5b), `scripts/loop_live.py`, one warm window, one permission:

- **O** "write a script that prints the primes under 50 and run it" — a
  `write_file`, a `run_command`, the output in the answer.
- **P** the PDF scenario from 4.3 — "make me a one-page PDF about X and
  send it": an install into the workspace, a run, `view_pages` or
  `read_document` on the result, `send_file`. Asserted on tools and
  outbound, not wording.
- **Q** a command that sleeps past its timeout — `timeout` in the result
  and the turn continuing.

Live, deployed (5a): the Volume round trip as its own line, then O, P, Q
through Telegram after the deploy, then the after-deploy run. Every
deployed command starts a container: a product-runtime worker and its own
gate during development.

Measured, into `reports/ml_work.jsonl`: **cold start of the command
container and the warm call**, seconds per scenario, the image size. The
cold-start number is what decides whether 180 s idle is right and whether
the image needs trimming; the human asked for it before anything is built
on it.

## 7. Size, order, gates

`app/tools/shell.py` (tool, `Runner`, `Finished`, `LocalRunner`) ~150 lines;
the deployed runner ~60 lines in `deploy/modal/control_app.py` beside the
renderer, its image ~15; modes ~60 across `base.py`, the settings and the
two adapters; brief ~15; tests ~180; scenarios ~60. No schema, no
migration, no model-app change.

Order: **5b first** — the tool, the contract, the modes, the offline tests
and the live suite all run here — then **5a** as the second runner and the
deploy. Gates: a separate start signal for each; the local live run; the
deploy; the after-deploy run.

## 8. What this document authorizes

Nothing. The shape is approved; implementation waits for its own start
signal.

## 9. 5b built, 2026-09-04

Built the same day on the human's start signal, in the tree, not deployed
(5b is the local profile; nothing here reaches the deployment until 5a).

- `app/tools/shell.py`: `run_command` over a one-method `Runner`;
  `LocalRunner` — a process in the workspace through the platform shell,
  the environment reduced by `command_environment` (what a shell needs,
  `HOME` and `USERPROFILE` in the workspace, `PYTHONUTF8`), a new process
  group, killed with its tree at the deadline (`taskkill /T` on Windows,
  `killpg` elsewhere) and on cancellation; output cut in the middle above
  16k characters; codes `shell.timeout`, `shell.not_started`. The
  capability `shell.run` is in the default grant; the registry owns the
  runner. The brief says where commands run in the runner's own words and
  to install into the workspace.
- The two modes: `Tool.mutates` on `write_file`, `edit_file`, `run_command`;
  `Toolbox.ask_for_changes` read by `requires_approval`; `app/agent/mode.py`
  with the marker `.agent/careful.on`; `Agent.toolbox` reads it; `/mode`,
  `/mode full`, `/mode careful` in Telegram, in the menu; "Running a
  command…" as the activity label.
- Offline: `tests/test_run_command.py` (17: the local runner for real —
  cwd, exit code, the withheld environment, the kill at the deadline, the
  kill on cancellation, the cut, a start failure; the projection through
  the executor with a fake runner; the grant, the brief, the modes, the
  marker, the agent reading it) and one Telegram test of `/mode`;
  the whole suite 1044 passed, 27 skipped.
- Live, this machine, one warm window: **O** passed (write_file,
  run_command twice, the primes in the answer, 16.4 s, ~20 s derived GPU);
  **P** passed (`pip install reportlab`, a script written and run,
  `read_document` on the PDF, `send_file`, 13.2 s, ~25 s derived) — the 4.3
  acceptance that waited for generic execution, met without a PDF-specific
  workflow; **Q** passed (`shell.timeout` at 3 s, the model said so, 5.1 s).
- One observation from P, recorded as ISS-0038: the install went to the
  machine's global Python, not a workspace venv, against the brief's
  sentence in the same prompt. Two levers, for the human to choose between
  or defer: measure it (a sentence is the instructions lever, and one turn
  is not a rate), or make it structural the way `HOME` already is — an
  environment in which an install lands in the workspace (`PYTHONUSERBASE`
  and `PIP_USER`, `npm_config_prefix`), which is a general property of
  the runner rather than a rule about pip, but has a known snag:
  `PIP_USER` breaks `pip` inside a venv, so it would need care or a
  different mechanism. Not built.
- Not in 5b, by the approved shape: background processes, the deployed
  runner, the Chainlit `/mode` (Chainlit has no `/plan` either).

