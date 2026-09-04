# Version 2 — 5 isolated execution, against the references

**Date:** 2026-09-04
**Agent:** Claude, direct session
**Status:** analysis and a proposed shape. Step 5 was selected by the human
on 2026-09-04 and split on their word into the deployed profile (5a, Modal)
and the local one (5b). Nothing here is built; the shapes in §5 are options
until the human approves them in words, and implementation is a separate
start signal.

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

## 5. Options

### 5a — Deployed (Modal)

- **A — Modal Sandbox per person, by name (recommended).** One sandbox per
  workspace scope, `name=<scope>`, created on the first command and found
  again with `Sandbox.from_name` on every later one, from any worker
  container. Image: the agent image's runtime layers without the repository
  source, plus Python, Node and the usual build tools; **no secret**; the
  `assistant-workspaces` Volume mounted at `/workspaces`, `workdir` the
  person's directory. `idle_timeout` on the order of ten minutes, `timeout`
  the 24 h ceiling, so a coding session keeps its installed packages and
  running server across turns and dies quietly after. Cost: while alive
  only, ~$0.12/h at 1 CPU / 2 GiB; an hour-long session is cents, and the
  idle timeout bounds what a forgotten one costs. Network on in v1 (§4.4
  above); `outbound_cidr_allowlist` is one parameter away if evidence asks
  for it. Filesystem snapshots (an Image of the installed packages) are v2.
  The one thing to verify live before building on it: **the Volume seen
  from both sides.** The worker reloads before the turn and commits after;
  a file the sandbox writes must be visible to `read_file` in the same turn
  and to `send_file`, and a file `write_file` makes must be visible to the
  next `exec`. Modal Volumes allow concurrent mounts and commit/reload
  explicitly; the first live scenario is exactly this round trip, and if it
  fails, the fallback is OpenClaw's: the file tools move inside the sandbox
  for the deployed profile (they already take a root; a root that is a
  sandbox path is the second implementation the tool-system doc
  anticipated).
- **B — The worker's own process, secret scrubbed.** Cheapest; nothing to
  start. But the volume, the database socket and the network are the
  worker's, and "no control-plane secret" holds only for environment
  variables. Rejected: it is not the boundary the product contract names.
- **C — A separate Function without secrets.** Cold per command, `pip
  install` gone by the next call, no server survives. Rejected: it cannot
  do what the step is for.

### 5b — Local (this machine)

- **A — WSL2, `bubblewrap` around the workspace (recommended).** Commands
  run as `wsl -d Ubuntu -- bwrap …` with the person's workspace bound
  read-write at a fixed path, `/tmp` private, the rest of the filesystem
  read-only, an empty environment plus `PATH`, `HOME` inside the workspace,
  and the network left on in v1 (`--unshare-net` is one flag when wanted).
  The same primitive Claude Code and Codex use on WSL2, the toolchain is
  the WSL one the human already works in, no daemon. Known cost: the
  workspace lives on the Windows disk, so from WSL it is `/mnt/d/…` over
  drvfs, and `npm install` there is slow. If that hurts, the local workspace
  moves into the WSL filesystem, which is a configuration, not a design.
  Honest fallback, as the references do it: when `bwrap` is missing the
  tool runs the command in WSL without it, **and says so in the brief and
  in the result**, never silently.
- **B — The Windows host process.** No primitive to fence it; Codex's native
  Windows sandbox is its own low-privilege user and ACLs, not something to
  rebuild here. Acceptable only as the fallback above, not as the design.
- **C — Docker Desktop.** A daemon, an image, a second copy of the
  toolchain, for the same boundary A gives in a process. Not for v1.

### Common to both: the tool and its contract

One tool, `run_command(command, timeout_seconds=120)`, not `replay_safe`,
`delivers=False`. A fresh shell per command in the workspace; the result is
the exit code and the bounded output (the executor's head and tail already
do this), with the working directory and the elapsed time. A timeout kills
the process tree and reports `timeout` through the existing code. A command
blocked by the boundary reports what was refused (the path, or the network)
the way Claude Code does, so the model can say so or do otherwise. No
per-command consent inside the boundary (`DECISIONS.md` 2026-08-30); the
tool is not in the approval-gated set. Background processes (a dev server
the browser then looks at) are **v2**: they need a `process` handle and a
lifetime tied to the sandbox, and `inspect_page` already serves workspace
files without one. The brief gains one paragraph: where commands run, that
the workspace is the only writable place, whether network is on, and — in
the fallback — that there is no isolation.

Behind the tool, one small protocol, `Runner.run(command, cwd, timeout) ->
Finished(exit_code, output, cut)`, with `WslRunner` and `ModalSandboxRunner`
chosen by profile in `create_agent`, the way `open_store` picks the store.
Not a `BaseEnvironment` hierarchy: two implementations, one method.

## 6. Acceptance: the suite is the instrument

Offline (`tests/test_run_command.py`): a fake runner through the executor —
exit code and output projected, a timeout reported with the code, output
over the bound cut with head and tail, the tool absent from the approval
set; `WslRunner` unit-tested on the command line it builds, not by running
WSL.

Live, local (5b), `scripts/loop_live.py`, one warm window, one permission:

- **O** "write a script that prints the primes under 50 and run it" — a
  `write_file`, a `run_command`, the output in the answer.
- **P** the PDF scenario from 4.3 — "make me a one-page PDF about X and send
  it": `pip install` of a PDF library, a run, `view_pages` or `read_document`
  on the result, `send_file`. Asserted on tools and outbound, not wording.
- **Q** a command that sleeps past its timeout — `timeout` in the result and
  the turn continuing.
- **R** a command that writes outside the workspace — refused by the
  boundary, the refusal in the result. Skipped, and said so, when `bwrap` is
  absent.

Live, deployed (5a): the same O, P, Q through Telegram after the deploy,
plus the after-deploy run; and before them the Volume round trip named in
§5a A, as its own line. Every deployed command starts a Sandbox: a
product-runtime worker and its own gate during development.

Measured, into `reports/ml_work.jsonl`: sandbox creation latency cold and
reattached, seconds alive per scenario, the cost per session at the chosen
idle timeout.

## 7. Size, order, gates

`app/tools/shell.py` (tool, `Runner`, `Finished`, `WslRunner`) ~150 lines;
`ModalSandboxRunner` ~80 lines in `deploy/modal/` beside the renderer, since
it is deployment-specific; wiring and brief ~40; tests ~150; scenarios ~80.
No schema, no migration. A new Modal image for the sandbox; a model-app
redeploy is not involved.

Order proposed: **5b first**, because the tool, the contract, the offline
tests and the live suite all run on this machine and cost nothing, then
**5a** as the second runner plus the deploy. The alternative — 5a first,
because the product is the deployed one — pays a Sandbox start for every
iteration of the tool's own contract.

Gates: the human's word on §5 (the shapes for 5a and 5b, network on, the
order), then a separate start signal for each; the local live run; the
deploy; the after-deploy run.

## 8. What this document does not authorize

No implementation, no Sandbox, no GPU run, no deploy.
