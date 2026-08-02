# Version 1.5 step 3 — unified natural-language entry

**Date:** 2026-08-02

## Outcome

The rejected `Conversation` / `Agent` selector and its UI-owned routing state
were removed. Every ordinary Chainlit message now enters `GeneralHarness`, which
asks the model for a strict `answer` or `act` decision. Chainlit renders the
chosen path but does not select it.

The routing request receives the same bounded conversation layers as the normal
agent, including summary, recent history and retrieved memory. An invalid or
failed routing response falls back to the normal conversational agent, which can
answer, clarify or use its governed tools.

Task input and the final task outcome are recorded in the canonical SQLite
conversation rather than existing only as transient Chainlit steps.

## Offline checks

```text
python -m pytest -q
308 passed in 7.34s

python -m compileall -q app ui
passed

git diff --check
passed
```

The regression suite includes strict route parsing, model-owned answer/act
selection, multimodal routing input, bounded history availability, safe routing
fallback, canonical task persistence and a static assertion that Chainlit has no
mode settings route.

## Actual app smoke

The already running local model endpoint reported:

```text
model: gemma-4-12b-it
max_model_len: 16384
```

Chainlit was restarted with the changed application and listened on
`http://127.0.0.1:8100` (HTTP 200). Browser inspection found one ordinary message
textbox and no `Mode` selector.

Two requests were submitted through that same textbox:

1. `Ответь кратко: сколько будет два плюс два?`
   - routed to the normal answer path;
   - visible answer: `Четыре.`;
   - reported request fill: `912 / 9830 tokens (9%)`.
2. Create `D:\ML\local-multimodal-agent\workspace\step3-smoke.txt` containing
   `STEP3-OK`.
   - routed by the model into the bounded task lifecycle;
   - produced a plan and task-specific acceptance criteria;
   - asked for one workspace grant with `filesystem.read` and
     `filesystem.write`;
   - after the already authorized local smoke action, completed in one iteration
     and two tool calls;
   - the application check reported a non-empty 10-byte artifact;
   - direct filesystem inspection confirmed `STEP3-OK<CR><LF>`;
   - the temporary smoke artifact was removed after verification.

The restarted Chainlit error log was empty. The local model server was not
restarted and VRAM was not measured.

## Remaining limitation

Step 3 proves one model-routed entry and both real paths. The task runtime's
current default verifier only proves that reported artifacts exist and are
non-empty. Deriving and evaluating semantic evidence against task-specific
criteria remains Version 1.5 step 4.
