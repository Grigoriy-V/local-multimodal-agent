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

**OpenClaw on a VPS, read 2026-09-04 before step 5 started** (sandboxing,
exec, exec-approvals, security, workspace and Docker pages). Their main
mode is the agent on the operator's own server, and it is our shape: the
sandbox is **off** by default, `exec` runs on the gateway host with
`security: "full"`, `ask: "off"`, described as "one trust boundary per
gateway: a single operator" and a supported deployment; the boundary is the
VPS or an OS user, and the agent there can reach credentials and env, which
they advise keeping out of its paths — we keep the secret out of the runner
altogether. The Docker sandbox is opt-in for foreign senders and
multi-agent setups (one container per agent, workspace hidden, network
none): our v2. In their Docker install the gateway container is disposable
and three bind-mounted directories — state, workspace, keys — are what
lives: our Volume. The workspace is auto-initialised as a git repository
and they urge a private remote as backup and rollback. No shell state
carries between `exec` calls; `process` backgrounds after 10 s. `exec`
modes `deny` / `allowlist` / `ask` / `auto` / `full`, an "allow always"
answer bound to exact argv and cwd in SQLite, a model reviewer in `auto`,
and `askFallback: deny` when nobody can be asked — our "nowhere to ask
means no". Default `exec` timeout 1800 s against our 120 default and 600
ceiling. Taken: nothing changes in step 5. Recorded as options: raise the
ceiling to 1800 on the first live case that needs it; "allow always" for
the careful mode once it is used (item 7); git in the workspace as the
Volume's undo; a secret-substituting egress proxy when a command must use
the person's own keys (v2).

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
- One observation from P, ISS-0038: the first install went to the
  machine's global Python, not a workspace venv, against the brief's
  sentence in the same prompt. The human's rule, the same day: this must
  not be possible; the agent works in the project, and global is the
  person's own explicit act. Made structural, the way `HOME` already was:
  the runner makes the workspace's virtual environment on first use and
  puts it first on `PATH`, so `python` and `pip` are the workspace's;
  `PIP_REQUIRE_VIRTUALENV=1` makes pip refuse every other interpreter;
  `npm_config_prefix` sends a global npm install into the workspace. No
  rule about pip in the prompt and nothing that reads the command. P
  re-run: the install landed in `.venv` (30 s with the venv creation and
  a full download, ~35 s derived GPU). Deployed (5a) the same layout on
  the Volume is what makes installs survive the container.
- Not in 5b, by the approved shape: background processes, the deployed
  runner, the Chainlit `/mode` (Chainlit has no `/plan` either).

## 10. The write boundary on native Windows, 2026-09-04

The human read the two installer rules (`PIP_REQUIRE_VIRTUALENV`,
`npm_config_prefix`) as a crutch and asked for the references' property
instead: a command writes only inside the workspace, whatever it is. On
macOS and Linux the references get it from Seatbelt and bubblewrap; Codex on
native Windows from a dedicated low-privilege user or an "unelevated
ACL-based" fallback; **DeepSeek Harness** (`packages/sandbox/sandbox-windows-acl`,
read the same day when the human asked what it does) from a
**write-restricted token** with the workspace granted by ACL — with the
documented partial case that Everyone must stay in the restricting list, so
a place Everyone may write to stays writable, and that hard links alias a
file across the boundary.

The first attempt here failed: every process beyond `cmd` died at
initialization (`STATUS_DLL_INIT_FAILED`), and the report said so and listed
a second user, WSL2 or no boundary as what remained. Reading DeepSeek's
`token.ts` and README and then probing this machine step by step found the
four things that make it work, none in the API reference, all now in the
docstring of `app/tools/shell_windows.py`: the logon SID and Everyone in the
restricting list (DeepSeek's note); **no `LUA_TOKEN`**, which DeepSeek sets
and which on this machine turns Administrators deny-only and locks the
command out of a workspace it owns through that group; the token's
**default DACL** extended to the restricting identities, or a grandchild
(everything `cmd` starts) fails the same way; and the command **inheriting
a console** rather than getting its own, with the output in a file in the
workspace's temp rather than a pipe — a new console fails at
initialization, `cmd` without any console hands its children dead standard
handles even unrestricted, and a pipe carries no ACL the restricted
grandchild could pass. The agent process allocates a hidden console once
when it has none. `pywin32` (already in the lock through a dependency) is
declared for Windows in the `app` group.

One more thing the first live rerun found: three `pip install` hanging to
their 120 s deadline. `tempfile.mkdtemp` — pip's build and download
directories — asks `os.mkdir` for mode 0o700, and CPython on Windows gives
such a directory an explicit owner-only ACL (SYSTEM, Administrators, OWNER
RIGHTS) in place of the inherited one; the restricted command cannot use it,
and `tempfile` tries thousands of names before giving up. The token's owner
cannot be changed to an identity that ACL admits (`ERROR_INVALID_OWNER`),
and admitting OWNER RIGHTS to the restricting list opens every file the
person owns — measured: a file outside the workspace written, its ACL
changed. So the workspace's own venv, and only it, carries a
`sitecustomize.py` that makes a 0o700 directory like any other; nothing
else is patched, and node, git and the shell are untouched. Said plainly:
an accommodation of one interpreter behaviour, in the place that
interpreter lives, so the boundary can stay a boundary on every write.

Measured, `tests/test_run_command.py`: a write inside the workspace and in
a directory that existed before the grant succeeds; a write beside the
workspace, into the base Python's directory and into the person's profile
is refused by the OS with `PermissionError`; `git --version` and a `python`
started by `cmd` both reach the output; the kill at the deadline and on
cancellation still hold; a temporary directory and a temporary file are
made and used inside the workspace; a real `pip install reportlab` lands
in the workspace venv in ten seconds. The two installer rules are gone.
Live: O passed (18.6 s), Q passed (5.8 s); P made the PDF under the boundary (`pip install reportlab` in 6.5 s into the workspace venv, the script run) and then failed its look-and-send checks on the model's side — it did not trust a successful command with no output, tried `python3` (not on Windows), re-ran the same script until the repeat guard stopped it, and answered without `read_document` or `send_file` (ISS-0039). The first rerun before the accommodation had P hang three times on `pip install` (120 s each), which is what found the 0o700 case.
The whole suite after all of it: 1051 passed, 27 skipped.

What stays partial, as in DeepSeek: a directory Everyone may write to
(`C:\Users\Public`) is writable; a hard link is one file on both sides.
Reading and the network are untouched, by design. On a non-Windows local
profile there is still no boundary and the brief says so.

Left as built: the workspace venv as the project environment (not a crutch:
every reference runs commands in the project's environment), temp and
profile directories inside the workspace.

## 11. The automatic venv, and the local profile set apart, 2026-09-04

Asked whether the automatic `.venv` in the workspace is a crutch by the
same rule, the answer is yes: a rule about one toolchain (Python gets a
special environment, node, cargo and go do not), whose local reason — keep
`pip` out of the machine's Python — the boundary now serves on its own, and
whose deployed reason — what is installed must survive the container — the
model can meet the way a developer does, with a venv when the project needs
one. The references do none of this: Claude Code and Codex run `python` as
the developer's shell would, with the machine's packages, and a venv is the
developer's decision. The isolated venv also hides what the machine already
has, so `reportlab` was downloaded onto a machine that has it.

Agreed in discussion, not built: remove the automatic venv and the `PATH`
change; keep what is general (the workspace as cwd, home, temp and profile;
the reduced environment); move the CPython 0o700 accommodation to a
`sitecustomize.py` on `PYTHONPATH` under the workspace's `.tmp`, which every
Python — the machine's and any venv the model makes — picks up; say in the
brief that `python` and its packages are the machine's, that what is there
is to be used, and that installing is possible only into a venv inside the
workspace. Cost: on the first `pip install` a refusal from the OS and one
step to make a venv, when the brief has not already said so.

Then the human's larger reading, recorded on their word: local work on
files — one's own projects, on one's own machine, through the local UI,
which today has no way to choose a project folder — is a stage of its own
with its own problems, not a sub-step of the sandbox, and not the place to
go now. What 5b built stays and is kept (`ROADMAP.md` item 7, with the open
points listed there); item 5 is the deployed profile alone, where the
container is the boundary, none of the Windows mechanics apply, and the
same rule holds for installs: base tools in the image, a venv in the
workspace only when a project needs its own.

## 12. Step 5 built, 2026-09-04

Started on the human's word after the OpenClaw reading (§3). What was built,
against the shape in §5:

- **The Function.** `run_command(workspace, command, timeout)` in
  `deploy/modal/control_app.py`, on `command_image` — the worker's
  dependency layers plus `BASE_TOOLS` (`nodejs`, `npm`, `git`, `curl`,
  `zip`, `unzip`, `tar`, `jq`, `ffmpeg`, `imagemagick`, `poppler-utils`,
  `pandoc`), the source copied last, no browser — with the workspaces
  Volume, **no secret**, 1 CPU, 2 GiB, `scaledown_window=180`, `timeout=660`
  (above the tool's 600 s ceiling, so the runner is what kills a command
  and the partial output is kept). `workspace` is a directory name resolved
  under `/workspaces` and refused if it climbs out; the directory is made
  if missing. The Volume is reloaded before the command and committed
  after. A container-global count makes the first command in a fresh
  container say `new environment`. The result is a dictionary, `failure`
  carrying the runner's own code when there is one.
- **The runner.** `ModalRunner` beside the worker: commits the Volume,
  calls the Function with `.remote.aio`, reloads, and raises the same typed
  `ToolError` a local failure would. `seconds` is the whole wait, container
  included. Its `where` tells the model what is installed, that the
  container is disposable, that a venv in the workspace is the way to
  install Python packages and that node packages land there on their own.
- **The seam.** `create_agent(runner=)` and `TelegramAdapter(runner=)`; the
  worker and `self_test` pass `ModalRunner()`, asserted by a test, because
  the default is a `LocalRunner` and that would be a process beside the
  secrets. `LocalRunner.prepare` is the hook the container's
  `ContainerRunner` overrides to make no venv (§11: not the model's
  decision on Modal either). `command_environment` puts `.venv` first on
  `PATH` only when it exists; locally it always does. The brief's sentence
  about what survives moved out of `app/capabilities.py` into the runner's
  `where`, since it differs.
- **Not done, by choice.** The Volume is mounted whole, as in the worker;
  one operator today, and a command in one person's directory can reach
  another's. Recorded in the Function's comment; the fix is mounting one
  directory at a time when there is a second person.

Measured offline: `tests/test_modal_control_app.py` (seven: the Function
holds no secret and gets the Volume, the image carries the base tools and no
browser, the worker and the self-test pass the runner, commit/reload order
on both sides, the path check, the `where` text) and
`tests/test_run_command.py` (three: a workspace without a venv keeps the
machine's Python, `ContainerRunner` makes the temp and no venv,
`create_agent` hands the runner to the registry), one adapter test; the
whole suite below. `deploy/modal/control_app.py` imports and builds its
objects locally.

Not measured yet, each a container start and its own permission: the
deploy; the round trip (a file from `write_file` seen by the command, a file
from the command seen by `read_file`, same turn); the cold-start number
(`scripts/measure_command_cold_start.py`); O, P, Q through Telegram; the
after-deploy run.

**Deployed and measured, 2026-09-04.** `modal deploy` in 107 s, the
`command_image` built once. `scripts/measure_command_cold_start.py`, two
invocations from this machine, the second right after the first:

| run | waited | command | container | inside |
|---|---|---|---|---|
| cold | 8.49 s | 0.20 s | 8.29 s | Python 3.12.10, node 18.20.4, git 2.39.5 |
| warm | 0.81 s | 0.11 s | 0.69 s | same |

The container's share of a cold command is about eight seconds — more than
the worker's own 4.9 s, because this image is larger and its first execution
imports the tools module. A warm call costs under a second of round trip,
Volume commit and reload on the worker's side not yet included. What this
says for the person: the first command of a piece of work waits eight
seconds once; the rest, within three minutes of each other, wait under one.

**Live through Telegram, 2026-09-04, three messages from the human**
(runs `c089c570`, `a3ef6a14`, `3f51cd70`, and a fourth, `3935092c`, when
the human asked again about the PDF):

| | tools | run_command | turn | what it showed |
|---|---|---|---|---|
| O, primes | `write_file` → `run_command` | 2.78 s | 23.9 s | the file from `write_file` was there for the command: the worker's commit before the call works |
| P, PDF | `write_file` → `run_command` → `send_file` | 23.68 s | 55.9 s | `pip install reportlab` into a venv the model made in the workspace (`.venv` is on the Volume), the PDF from the command was there for `send_file`: the reload after the call works. **No look at the document** — ISS-0040 |
| Q, timeout | `run_command` failed `shell.timeout` | 6.17 s | 14.4 s | the code reached the model and the turn went on |
| P again | same three | 2.53 s | 32.1 s | the venv on the Volume served the second run in a warm container; still no look |

The round trip holds in both directions, and what was installed survived
into the next turn on the Volume. The Function's `seconds` is the whole
wait: O's 2.78 s is a warm container after the cold-start probe.

**What the person saw:** the PDF came as black squares. The model's script
used reportlab's built-in Helvetica for Russian text, and there is no glyph
for Cyrillic in it; the container had no font at all — `debian_slim` ships
none, and the renderer's image had `fonts-dejavu-core` added for exactly
this ("a screenshot of Cyrillic is a row of boxes"). Sorted by the rule:
the missing font is the **harness's** — a place where documents are made
for a person who writes Russian needs a font with Cyrillic, the same
property the renderer already has — and `fonts-dejavu-core` and
`fonts-liberation` are now in `BASE_TOOLS`, with the runner's `where`
saying where the TrueType files are. Not looking at the PDF before sending
it, twice, is the **model's** (ISS-0040), the brief already asks for the
look, and it is measured by P, not scripted. Asked to fix it, the model
did — the second PDF was readable, in English, the human notes — by
dropping the Russian text rather than registering a font it did not know
it had; with the fonts named in `where`, that is the next P's question.

**P in Russian after the font deploy, 2026-09-04** (runs `8fd21453`,
`510fe752`, thread `cd74d869`). The first message, in the old thread, got a
`send_file` of a `tea_info.pdf` that had not been made — `fs.not_found`
came back and the model answered in text. In a fresh thread: `pip install
fpdf2` into the workspace venv, **97 s** (fonttools, 5.4 MB, hundreds of
files written to the Volume; reportlab had taken 23.7 s earlier — a venv on
a Modal Volume pays per file, a measured cost of the shape, not a defect),
then six rewrites of the script through `cat << EOF`, each failing on
fpdf2's own API (a bold style never registered, deprecated arguments), each
about 3 s to run and 10–20 s to generate, until the human stopped the turn
at 200 s; `turn_stopped` landed cleanly and the seventh command was not
run. The font was there: the script tested for
`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` and registered it — the
errors were about the bold variant it had not registered. Sorted by the
rule: the harness did what it was built to do — the round trip, the fonts,
the stop, the errors reaching the model verbatim; the rest is the model's,
measured by P: it chose a library it does not know well over the one
already installed, and debugged by rewriting the whole file. Two options
for the model's side, both to be measured and neither built: a brief
sentence that an installed library is listed by `pip list`; and the
observation that fpdf2's traceback names the fix and the model did not
apply it, which is a question about the model, not about the tool.

**The working method, 2026-09-04.** Asked why the agent does not find out
what is there and check what it made, the answer was: the model's habit,
not the harness's mechanism — Claude Code and Codex get it from training
and from a system prompt that says so. On the human's word a block was
added to the stable prompt core (`WORKING_METHOD`, `app/context/window.py`):
find out with a tool before assuming, prefer what is there over installing,
check each result and open what was produced before handing it over, fix
the cause an error names rather than starting over, claim only what was
seen. A method, tested to name no tool, file type or library. About 130
tokens on every request. Not yet measured: the instrument is P again and
`tools/prompt_scenarios.py` with the previous prompt as the variant; the
deployed profile sees it after the next deploy.

**P in Russian with the working method, 2026-09-04** (run `3b3c86d8`,
thread `498a0aa2`, fresh thread, the block deployed). The same loop: `pip
install fpdf2` first (already installed — **55.5 s** for pip to say so, in
a fresh container against a venv on the Volume; 5.4 s warm), then
`python3 -m venv .venv && pip install` again, then six rewrites of the
script — the first run **50.7 s** (the venv's files read from the Volume for
the first time), the rest 2.4–3.5 s — and the human stopped it at 220 s.
One rewrite registered the bold face, which was the fix the error named,
but in the main body after `add_page()`, whose `header()` needs it first;
the model never saw the order. It did not run `pip list`, `ls` or
`fc-list`, and never opened a result, because no run produced one.

Measured, then: on this case the block changed nothing visible — one
observation, the same request, the same library, the same six rewrites.
What the block asks for is a habit this model does not have and one
paragraph does not give it; a stronger model, or a skill that carries the
knowledge (how a document is made and checked here), are the levers left,
and the human's call. Recorded rather than concluded: `prompt_scenarios`
with both prompts is the instrument for a claim either way.

Two harness numbers from the same run, both the Volume's: a no-op `pip
install` at 55 s cold and the first import of a Volume venv at 50 s. Modal
documents the cause — a Volume is made for large files, not thousands of
small ones, which is what a site-packages is. Options, unbuilt: the common
document and data libraries in `command_image` beside the base tools, so a
venv is the exception rather than the first step (a human's list, and a
rebuild per change); or accept the cost as the price of an install that
survives.

**What DeepSeek Harness has for "make the model an agent", read 2026-09-04**
(`packages/core/system-prompt`, `preset/agent-presets/presets/standard`,
`shell/tool-bash`, `fs/tool-fs`, `fs/fs-observation-policy`,
`guard/repeat-tool-reminder`, `plan`, `todo`, `goal`, `hooks`). There is no
global prompt block of the kind added here. The persona is one sentence
("You are a coding agent powered by {{model}}. Your working directory is
{{cwd}}."), and everything else is small and placed at the seam it is
about: a per-tool prompt section ("Check the [exit code: N] marker on every
bash result; investigate failures before moving on"; "Read the file first
… unless you just created or edited it"); a **tool-boundary policy**,
`fs-observation-policy`, under which an edit of a file the session has not
read fails with `FS_NOT_OBSERVED` and the remedy "read the file, then
retry", and a file changed since it was read fails `FS_STALE_VERSION` — a
mechanism, general (every file, every edit), stated as a property ("you
change what you have seen"); an **advisory repeat reminder** at 3, 5 and 8
identical calls; plan mode's section, which is the fullest prose they have
("Explore first … Resolve discoverable facts by inspection … Do not ask the
user where code lives when you can find out") and applies only while
planning; `todo_write` and a durable goal as state the model keeps; hooks
as the deployment's own reactions to tool results. The agentic habit itself
they take from the model (DeepSeek V4) — nothing in the harness pretends
to supply it. Read against ours: our repeat guard, typed failures with
remedies and tool-boundary policies (a path root, a `mutates` flag, the
write boundary) are the same kind of thing; what we do not have is a
per-tool sentence at the tool and an observation rule at the file seam.

**The harness's part in the loop, found 2026-09-04** when the human refused
"the model cannot" and asked for the harness: `stubbed` climbs 1→5 through
the run. The surface keeps two results verbatim and stubs the rest, and a
command's `exit code: 1` is a result, not a failure, so from the fourth
attempt on the model saw its earlier scripts whole and their tracebacks as
`[…; shortened, call the tool again for the full result]` — and attempt
four repeated attempt one. ISS-0041. The mirror of ISS-0022, where
shortening the model's *own* words made it rewrite every file: shortening
what the tools *said back* within the turn makes it repeat every mistake.
The rule's own reason — "the model has already said what it made of them"
— holds for a previous turn and not for the one in progress; and the stub
tells a command to run again.

Fixed the same day on the human's word: `shortened` stubs only stored
history; the turn's results stay whole whatever their number; the "call the
tool again" wording is gone with the case it served. `tests/test_context.py`
carries the six-traceback turn. To be measured: P in Russian again, after a
deploy.

**Two threads after the fix, 2026-09-04** (deploy v71 at 12:11 UTC; the
first thread ran at 11:54 on v70, before it).

*Tea in English* (run `558aa25c`, v70): `python3 -m venv .venv &&
.venv/bin/pip install fpdf` (33 s), `write_file`, `.venv/bin/python
make_pdf.py`, `send_file` — four tools, 100 s, the PDF delivered. No look
at it (ISS-0040 stands).

*Juice in Russian* (thread `30ed956f`, five turns, v71): `stubbed=0` on
every one of twelve steps of the first turn — the turn's results were all
visible, the fix holds. The model wrote a correct reportlab script with
`TTFont` registered from `/usr/share/fonts/truetype/dejavu/`, ran `pip
list` and `find /usr/share/fonts` when the human asked, and never got a
PDF, because every run was `python3 .venv/bin/python create_pdf.py` —
python running the venv's python *binary* as a script — answered six
times by `File ".venv/bin/python", line 1: ELF … source code cannot
contain null bytes`, with the traceback in full view each time. It blamed
`write_file`, made four more venvs (`.venv_new`, `.venv_ru`, `.venv_fpdf`,
`.venv_final`, 60 s of installs) and ended by handing the person the code
to run themselves. Sorted: the model's reading of an error that names its
own file on the first line. One harness observation beside it: the
runner's `where` carries a recipe — `python3 -m venv .venv &&
.venv/bin/pip install ...` — and the model ran that line, verbatim, as
the first command of every turn, venv or no venv. A brief that prescribes
a step gets the step; one that states a fact ("a `.venv` in the workspace
is the `python` a command gets") leaves the step to the model. Option,
unbuilt: `where` states facts and no commands.

**Built and deployed on the human's word, 2026-09-04:** `BASE_PACKAGES`
(reportlab, fpdf2, python-docx, openpyxl, pandas, matplotlib, Pillow, pypdf,
markdown) in `command_image` through `uv_pip_install` — a `pip_install`
layer failed on the first build because `uv_sync` makes the image's Python
a uv venv (`/.uv/.venv`) with no `pip` module — and the runner's `where`
rewritten as facts with no command in it. Deploy 28 s. Not yet measured:
the cold start with the larger image and the packages importable through
the command's `python3` (`scripts/measure_command_cold_start.py` now
imports all nine), and P in Russian on this image.

Measured on the new image, two invocations:

| run | waited | command | container | inside |
|---|---|---|---|---|
| cold | 10.61 s | 2.75 s | 7.86 s | all nine packages import through the command's `python3` |
| warm | 2.18 s | 1.60 s | 0.58 s | same |

The container's share did not grow (7.9 s against 8.3 s before, 0.6 against
0.7 warm); what grew is the command itself, because the probe now imports
pandas and matplotlib, which cost 1.5–2.5 s wherever they are.

**P in Russian on the new image, 2026-09-04** (run `a7d5c61c`, thread
`66d217fc`): no venv made, a reasonable fpdf2 script with `add_font` from
`/usr/share/fonts/truetype/dejavu/`, `ls` and `find` on the fonts on its
own, and every run failed inside `.venv/lib/python3.12/site-packages/fpdf/`
— the workspace's old `.venv`, first on the command's `PATH`, in which the
English-tea turn had installed **fpdf 1.7.2 over fpdf2**: `set_font` at
line 603, `RuntimeError: FPDF error`, `add_font` doing `pickle.load` are
fpdf 1.7, and `pip install fpdf2` answered "already satisfied" because
fpdf2's metadata was still there under fpdf 1.7's files. The image's fpdf2
was never reached. Twelve steps, the turn's budget, an honest text answer.
Why the first P of the day simply worked: a workspace with no venv,
reportlab, Helvetica. Sorted: the harness's — the container's `PATH`
prefers a `.venv` on the Volume silently, so the brief says fpdf2 is
installed and `python3` finds fpdf 1.7, and the workspace now carries five
venvs and a font directory from the day's experiments. Option: in the
container, the environment is the image's and a venv in the workspace is
used only when a command names it (the references' behaviour: nothing is
activated for the developer); and the debris on the Volume is the human's
to delete.

## 13. Where a conversation works: a directory of its own, and the person's files — option, 2026-09-04

The human's question after the venv-on-PATH finding: should a session get
a directory of its own, where the agent may make a venv and build things,
while still working on the files in the root — because nobody has hands on
the server, and everything landing in the root is "a sea of problems".
Today's root proves it: twenty `Task Board test N` directories, five venvs
and a `fonts/` from one day of tests, and a venv that poisoned the next
session's `python3`.

**OpenClaw** (`gateway/sandboxing`, read again for this): a sandboxed
session works in a **sandbox workspace of its own** under
`~/.openclaw/sandboxes`, one per agent, per session or shared by
configuration; the agent's main workspace is a separate directory, mounted
into the container read-only at `/agent` or read-write at `/workspace`
when the deployment allows, hidden by default; the sandbox workspace is
deleted with its container when pruned. Package installation is "image
provisioning, not normal sandbox-turn behaviour" — their answer to venvs
is the same as ours today, the libraries in the image. So their shape is
two directories: the session's, disposable, and the person's, shared and
mounted beside it.

**Claude Code and Codex** have one concept for this that OpenClaw's two
directories are a special case of: a **working directory** inside a
**boundary**. `cwd` is where relative paths go and new files land; the
boundary (the project, the allowed roots) is what may be touched at all;
`../x` is fine while it stays inside the boundary. Nothing is activated in
either.

**Option for us, not built:** keep the person's root (`/workspaces/<user>`)
as the boundary every tool validates against, as now, and give each
conversation a working directory inside it — `<user>/sessions/<thread>/`
— as the `cwd` of commands *and* the base of relative paths for the file
tools, so a command and `write_file` still agree on where `make_pdf.py`
is. The brief states two facts: the working directory is the
conversation's own, where new files and a venv land; the person's files
are one level up, reachable by `../name`, and `send_file` takes any path
inside the root. A `/new` starts in a fresh directory; the old one stays
on the Volume until the person deletes it (or a later rule prunes it).
What it costs: one `cwd` notion added to the registry (`Toolbox` roots
stay), a relative-path base in the file tools, the `where` and workspace
lines in the brief, and a scenario asserting a file made in the session
directory is found by a command and sent, and a file in the root is
readable by `../`. What it risks: the model reading `..` wrong, which the
suite measures. Not this: a per-session *root* (the person's files would
be unreachable), or a session directory only for commands (the round trip
would break on the first relative path).

**P in Russian on the clean workspace, 2026-09-04** (run `f25fd7cd`): the
image's fpdf2 reached (`/.uv/.venv/.../fpdf/fpdf.py`), no venv made, `ls`
on the fonts on its own, and four versions of `make_pdf.py`: DejaVu without
`add_font` (the error named it), Arial for Cyrillic (`latin-1`), a
version that was mostly a comment, then one with `add_font` for both faces
from `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` — plausibly the
right one — whose run the harness refused: "this exact call has already
succeeded twice in this turn with these same arguments" (ISS-0042). The
identical-success guard of ISS-0019 counts `python3 make_pdf.py` across
the turn, a non-zero exit is a success, and a rewrite of the file between
two runs reset nothing. Hermes's rule, read on 2026-09-03 and left as an
option, is now taken: a success of another workspace-changing tool between
two identical calls starts the count over; the same call unchanged three
times is still refused. The model's part: after the refusal it sent the
same line twice more and then the whole script as a `python3 -c` one-liner.

**P in Russian after the ISS-0042 deploy, 2026-09-04** (run `0876a984`):
every tool ran, nothing refused, nothing stubbed, the image's fpdf2 and
fonts in place. The model's first three scripts were the same three as the
previous run, word for word — the same prompt gives the same trajectory —
and at the fourth step, instead of the `ls` it did last time, it wrote a
text file and told the person a PDF with Cyrillic "requires external fonts
in the system", with the brief's own sentence naming
`/usr/share/fonts/truetype` (DejaVu, Liberation) in the same prompt and
the traceback saying `FPDF.add_font() beforehand`. Sorted: the model's.
Nothing in the harness touched this turn.

**The tool's own sentence, 2026-09-04, on the human's word:** `run_command`'s
line in the brief now says that a non-zero exit means the command did not
do what was meant, that the whole output is read before the next step,
that a traceback names file, line and cause and what it says to do is the
fix rather than a reason to start over or give up, and that "something is
missing here" is checked with a command before it is said — DeepSeek's
placement (beside the tool, not in the persona), about every command and
no particular failure. To be measured with P.

**P in Russian with the tool's own line, 2026-09-04** (thread `e8c54e07`,
run `3a37dccb` and three more turns). The human's reading: not a win, a
shift. The first turn: the same three scripts as every run today, then —
new — `pandoc tea.md -o чай.pdf` ("pdflatex not found": pandoc is in the
image without a PDF engine, a half-tool to fix or drop), `ls` and `find`
on the fonts on its own, and the budget reached with a Markdown handed
over. Asked "why can't you install them, ask the tool, read how": `pip
show fpdf2` → not found, `pip list` → pip, uv, wheel — **the environment
lied** (ISS-0043: `pip` on the command's `PATH` is the base interpreter's,
`python3` the uv venv's) — then `python3 -c "import reportlab"` → 5.0.1,
and the model said so and asked to go on. "Делай": `find` DejaVu,
reportlab with `TTFont` registered, `python3 make_tea_pdf.py` exit 0,
`send_file чай.pdf`. Delivered, in Russian, no look (ISS-0040). Its own
account of why not at once is a story; what the log says is that the two
steps it needed — check what is there, register the font the traceback
asked for — it took only when pushed, and that the check it did make was
answered wrongly by the harness. Also seen: 16–20 s for single commands
(`find`, `pandoc`, the first run) in a warm container — to be measured
apart from the model before it is called the Volume's commit and reload.

**P in Russian with `/plan` on, 2026-09-04** (run `effea350`, fresh
thread, the same image and fonts as the four runs before it): `todo_write`
with three items, the content written first as Markdown, then a script
that registered DejaVu from `/usr/share/fonts/truetype/dejavu/` at the
first attempt (`uni=True`, deprecated but working), two error rounds each
fixed from the traceback (a wrong `fpdf.constants` import removed), exit 0,
`send_file juice_info.pdf`. 95 s, nine model calls, delivered in Russian;
no look at it. The human asked whether the comparison is honest given the
font was already there: it is the same environment as the last four runs,
all of which had the font and the libraries, so the one thing that differed
is plan mode — and it is one sample, which is what `prompt_scenarios` with
`/plan` on and off exists to turn into a number.

**The harness's line on a non-zero exit, 2026-09-04, on the human's word**
(their ask all day: "on an error the harness should say why not — look at
what is there"): a command result with a non-zero exit code now ends with
`UNWANTED_EXIT` (`app/tools/shell.py`) — the command did not do what was
meant, read the output, the traceback names file, line and cause and what
it says to do is the fix, check with a command before deciding something
is missing. DeepSeek's remedy-on-failure, applied to the one result that
is not a failure by design and is read as one; about every command, tested
to name no file type. The same words as the tool's brief line, but at the
moment they matter. Deployed together with `pip` in the image (ISS-0043).

**Japan, plan on and plan off, after the `pip` + hint deploy, 2026-09-04.**
*Plan on* (run `e2a6471b`): todo, `search_web`, a 403 from Wikipedia, a
page fetched, the text written, then one command with `add_font('DejaVu',
'', 'DejaVuSans.ttf')` — `FileNotFoundError`, and the result ended with
the harness's line; the very next call was `find /usr/share/fonts/truetype
-name "*.ttf"`, the absolute path went into the script, exit 0,
`send_file japan.pdf`. Delivered in Russian, 90 s, eleven tools. *Plan
off* (run `55cf5fa9`): the text written, `set_font('DejaVu')` without
`add_font` — the error and the line — then Arial and **the text in
English** with a wrong keyword, then Helvetica and English, exit 0,
`send_file`, and an honest sentence that the built-in fonts do not carry
Cyrillic. Delivered, in the wrong language, 48 s. Asked to add pictures:
one search, then "I have no tool to download files" — with `curl` in the
image and named in `where`. Neither run looked at its PDF (ISS-0040).

Read together with the morning: from no PDF in five runs to a PDF in both,
and in the plan run the hint's own suggestion (`find`) was the next
command. What plan mode adds is what the no-plan run lacks — the request
held as a goal, so "in Russian" is not traded away for a green exit code.
That is the goal discussion, next.

## 14. The request as the turn's goal — option, 2026-09-04

**What was measured.** Japan, the same image, the same prompt: with `/plan`
on, a PDF in Russian; with it off, a PDF in English and a sentence
explaining why — the request traded for a green exit code. Every "not a
win but a shift" run of the day ended the same way: the model stopped
when it had *something*, not when it had what was asked. This is the
first measured benefit of plan mode, and not the one it was built for: the
list did not make the model plan better, it made it keep the request in
front of it until the list was closed, because `FinishesItsOwnList`
refuses an ending with open items.

**What the references do.** DeepSeek Harness: `goal` — one durable
objective per session, created and updated by the model with tools,
`/goal` for the human, and a `goal-round-driver` that turns an active goal
into rounds of work until it is complete or blocked. OpenClaw: no goal
object; a heartbeat and the session's own instructions. Claude Code and
Codex: the model's training; the harness only ends the turn when the
model stops.

**Option for us, not built.** The goal is the person's request — it
already exists in the turn, and asking the model to *create* one is a
second list to keep true. What is missing is the check at the end. A
turn that did work (at least one tool ran) does not end on the model's
first answer: the harness asks it one more question, without tools —
"The person asked: ‹the message›. Did what you did give them that, as
asked? Answer `done`, `blocked: ‹why›` or `not yet`." — and

- `done` ends the turn with the answer as it stands;
- `not yet` gives the tools back for another round, at most two more,
  inside the turn's existing budget;
- `blocked` ends the turn, and the answer must carry the reason (the
  model's own sentence, not a template).

One short model call per working turn (about a second and 200 tokens);
nothing for a turn that used no tool. It is plan mode's benefit without
the list, and `/plan` stays what it is. Compared with what the human
refused in 4.9 ("says what it saw"): that check was written from the
shape of one defect (a screenshot claimed, a tool not run); this one is
DeepSeek's round driver reduced to its smallest form, about every request
and no tool. The risk, and the measurement: a 12B model that answers
`done` reflexively, which the two Japan runs decide — the no-plan run's
English PDF against a request "in Russian" is exactly the question it
would be asked. If it says `done` there, the mechanism is worthless and
is not built; if it says `not yet` and the next round registers the
font, it is worth its second. The instrument is `prompt_scenarios` with
the check on and off. Recorded as an option; the human decides.

**Two more shapes of work with commands, 2026-09-04** (the human: one PDF
scenario is not enough): `scripts/loop_live.py` R — `sales.csv` seeded,
totals per region with a command, `chart.png`, `send_file`, the largest
total in the answer — and S — `calc.py` with `a - b` and a `check_calc.py`
that asserts `add(2, 3) == 5`, run, fixed, run again green. Both asserted
on files and the last exit code, not on the route. Found while writing R:
the model has **no tool to look at a PNG it made** — `view_pages` renders
PDF pages, `inspect_page` opens HTML, `read_file` reads text — so "open
what you produced and look at it" is impossible for a picture. A gap, not
a defect: the roadmap's, as "a file the model reads is shown in its own
kind" (`read_file` returning an image part for an image). Not run yet:
every run wakes the GPU.



**Built 2026-09-04, on the human's word:** `read_file` shows an image file
(png, jpg, jpeg, webp — the types the chat accepts from a person) as an
image part with one line naming it, instead of decoding it as text; the
tool's description and the workspace brief say so; R now checks that the
chart was looked at before it was sent. `tests/test_read_image.py`.
\n