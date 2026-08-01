# Version 1 native chat history

**Date:** 2026-08-01  
**Result:** completed

## Outcome

Chainlit's native sidebar now lists the conversations already held by
`MemoryStore`. Opening a sidebar item resumes that thread through
`on_chat_resume`; a new chat uses Chainlit's session id. Conversation content
continues to have one owner: `data/memory.sqlite3`. Chainlit step writes are not
stored a second time.

The local single-user identity uses transparent header authentication, which
Chainlit requires for native history. Its random signing key is stored outside
the repository under `%LOCALAPPDATA%/local-multimodal-agent/` and remains stable
across UI restarts.

## Checks

- `.venv\\Scripts\\python.exe -m pytest -q`: 189 passed in 3.76 s.
- `.venv\\Scripts\\python.exe -m compileall -q app ui tests`: passed.
- `git diff --check`: passed.
- Browser smoke at `http://127.0.0.1:8100`: both pre-existing chats appeared in
  the native left sidebar; one old thread restored its user and assistant
  messages.
- Restart smoke: after a second Chainlit process restart, the same thread URL,
  messages and sidebar entries were restored; a fresh browser tab reported no
  console errors.

## External actions and limits

Chainlit alone was restarted for the smoke test. The model endpoint was not
running and was not started, so the check used no model requests and no GPU
work. Creating a new persisted conversation through a live model turn remains
covered by the final end-to-end Version 1 smoke.
