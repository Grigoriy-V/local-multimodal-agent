# Version 2 step 2 — Telegram adapter

**Date:** 2026-08-28
**Result:** implemented and covered offline; real Telegram traffic reached the
adapter and was scoped correctly. Acceptance still needs one conversational turn,
which needs a model server the machine currently cannot run.

## Shape

`ui/telegram/` is three modules, split along the seam step 3 has to cut.

- `api.py` — the Bot API wire format and nothing else: `getUpdates`,
  `sendMessage`, `editMessageText`, `answerCallbackQuery`, `sendDocument`,
  `getFile` plus the file download. Written over `httpx` rather than adopting a
  bot framework, for the reason `OpenAICompatibleBackend` is written over
  `httpx` rather than a provider SDK: the surface needed is six methods, and a
  framework would bring its own event loop and handler registry to a project
  where LangGraph already owns orchestration.
- `adapter.py` — `TelegramAdapter.handle_update`, one coroutine over one
  update. No routing, tool, memory or validation logic; it calls the same
  `GeneralHarness` surface the Chainlit adapter calls.
- `run.py` — long polling. This is the module the deployed profile replaces.

Text is sent unformatted on purpose. Telegram's Markdown modes reject unbalanced
punctuation, and model output is where unbalanced punctuation comes from.

## The two properties the roadmap asked for

**Identity is mapped, never adopted.** `canonical_user_id` derives a UUID5 from
the Telegram account id under a fixed namespace, so the canonical identifier is
not Telegram's own and a later interface can address the same conversation. The
open conversation is the user's newest thread, so `/new` only has to create an
empty one — which puts that mapping in the store instead of in memory a restart
would lose. Replacing the derivation with a lookup table later changes nothing
outside that one function.

**Accepting an update is separate from answering it.** `handle_update` assumes
nothing about a caller that can be kept waiting. Locally, `PollingBot` drives
it; in the deployed profile a webhook hands the same call to a spawned worker
and answers Telegram immediately.

Consent reuses the durable interrupts rather than inventing adapter state. The
pending question already lives in the checkpoint, so a callback reads it back
with `agent.pending` or `task_view().interrupt` and resumes. A restart between
the question and the answer loses nothing.

## Access

`TELEGRAM_ALLOWED_USERS` is a comma-separated list of numeric Telegram ids and
**empty means nobody** — the same reasoning as the workspace default: the safe
answer has to be the default, because a bot whose URL leaks spends the owner's
GPU and reads the owner's memory. The entry point refuses to start with an empty
list rather than starting open.

## Shared code rather than a second policy

Telegram delivers file contents, not paths. Instead of writing them to disk to
reuse the path-based admission policy, `app/attachments.py` gained
`load_attachment_bytes` and both paths now share `_check_count`, `_check_kind`,
`_check_size` and `_check_total`. There is still one place that decides what the
model is allowed to see.

## Checks

- Full offline suite: **383 passed in 10.18s** (340 before; 43 new). No network.
- `tests/test_telegram_adapter.py` replaces Telegram with an
  `httpx.MockTransport`, so the real wire format in `api.py` is exercised rather
  than mocked away, and drives the model with the shared `ScriptedBackend`.
  Covered: identity mapping and its stability across a store reopen; the newest
  thread being the open one; `/new`; update reduction including the largest
  photo size, captions and callbacks; a stranger being refused with nothing
  reaching the model; an empty allow list admitting nobody; an ordinary message
  answered into the chat; conversations stored under the mapped user and
  invisible to another; a photo becoming model input; an unsupported upload
  refused before the model; a work request offering the workspace grant as two
  buttons with its acceptance criteria; declining leaving no file behind; a
  failing turn answering instead of killing the bot; long answers split.
- `ruff check` clean on every new file.
- Entry-point guards, run for real: no token and empty allow list each refuse to
  start with the specific message.
- Default wiring built without the test seam: the allow list parsed, a harness
  constructed over `OpenAICompatibleBackend`, and a canonical thread resolved —
  with no model call made.

## Known limitation

Updates from different chats run concurrently; updates from one chat are
serialized so an approval cannot overtake its question. The consequence is that
`/stop` sent while that same chat is mid-task is processed after the task
finishes, not during it. In the deployed profile this disappears, because each
update becomes its own worker and cancellation goes through the durable task
state.

## Open access, added on request

`TELEGRAM_OPEN_ACCESS` admits every account instead of consulting the list. It
is never the default, the entry point prints what it costs when it is on, and
open access does not merge people: each account still maps to its own canonical
user. Three tests cover it, including that a stranger admitted this way still
gets their own conversation.

## Per-user files, added on request

Raising the switch exposed a gap that predates both steps: `create_agent` handed
every user the same `AGENT_WORKSPACE`, so the conversational file tools could
read across people. This was never in the step 1 scope — that scoped
conversations, summaries and memory — and it was the original single-user
design rather than a regression. It was demonstrated before the fix: one user's
ordinary toolbox listed another's task directory and read the file in it.

`user_workspace(root, user_id)` now gives each person their own root, and
`create_agent` goes through it. Identifiers that already look like a safe
directory name are used unchanged so the workspace stays readable; anything else
is hashed, because substituting bad characters could land two people in one
directory. After the fix the same demonstration returns
`outside the allowed root` for both the relative and the absolute path.

`scripts/migrate_workspace.py` moved the existing local workspace under
`workspace/local-user/` — 4 entries, dry run first, idempotent on re-run. It is
a script rather than start-up behaviour because a directory has no
`user_version` to state its shape, and moving someone's files is a poor place
to guess.

## Real Telegram traffic

The bot was started against the configured token and reached Telegram over long
polling — no public URL, which is a webhook requirement rather than a Bot API
one. `getMe` identified the bot; the allow list held one account.

A message sent from the allowed account was accepted and recorded under the
derived owner `d992be3b-ad26-…`, not under the Telegram account id, in a thread
separate from the three `local-user` threads already in the database. The
adapter created that person's own workspace directory next to `local-user/`.
That is step 1's scoping and the new file isolation both observed on real
traffic rather than in a fixture.

The thread holds no messages, which is correct: with no model endpoint the turn
fails before anything is persisted.

## Not done

- No conversational turn end to end. The machine currently has no GPU, so there
  is no model server to answer one. Acceptance of step 2 waits for that.
- Nothing was committed.

No external call beyond Telegram itself, no GPU work, no monetary cost.
