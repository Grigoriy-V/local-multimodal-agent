# Version 2 step 4.3.5 — prompt assembly and standing instructions

**Date:** 2026-08-30
**Agent:** Claude, direct session
**Status:** implemented, measured live, deployed. Two findings the measurement
produced are not fixed here.

## What changed

The system layer is assembled from parts instead of written as one paragraph.
The core in `app/context/window.py` is four sentences that name no tool, no
format and no workflow, and a test enforces that. Everything true only because
a capability is wired up is generated from the wiring in `app/capabilities.py`;
what each call does is owned by its tool schema. Layers are ordered by how
rarely each changes — core, capability guidance, schemas, the person's standing
instructions, summary, retrieved facts, history — which is also the order a
served prefix cache needs. 4.6a measures that; nothing here claims it.

Two sentences the old prompt could not contain, both from the 2026-08-30
measurement:

- the agent is told the actual path of its own workspace, and that it may read,
  create and change files there without asking;
- when the person asks for something that is a file and names none, it chooses
  a name, creates it and says which name it used.

`app/instructions.py` gives each person one `AGENTS.md` at the root of their own
workspace, read again on every turn and carried as its own framed message below
product and capability policy. It is not memory. `/agents` shows, replaces and
clears the same file, and is declared model-free at the front door with its
arguments, so saving a sentence cannot wake a GPU — the defect that would
otherwise have shipped. `DECISIONS.md` 2026-08-30.

Offline: **814 passed, 27 skipped**, 22 of them new.

## Live result

Nine scenarios through the same agent the bot uses, against today's baseline.
`reports/prompt_runs/2026-08-30_0809_after_assembly/`, derived cost **$0.0794**.

| scenario | before | after |
| --- | --- | --- |
| chat | 1 model, no tools | 1 model, no tools |
| capabilities | 1 model, no tools | 1 model, no tools |
| note | 3 model, `list_files`+`write_file` | **2 model**, `write_file` |
| castle | 1 model, **no tools** | **2 model, `write_file`** |
| castle_seeded | 1 model, **no tools** | **2 model, `write_file`** |
| castle_named | 2 model, `write_file` | 2 model, `write_file` |
| castle_after | 2 model, `write_file` | 2 model, `write_file` |
| broken_page | 3 model, `list_files`+`read_file` | 3 model, `list_files`+**`inspect_page`** |
| standing_instructions | — | 1 model, no tools |

The regression that blocked 4.3 is gone. A request that names no file, in an
empty workspace, now produces the file. The conversational scenarios still cost
one model call and no tool, and `note` got a step cheaper: with the workspace
named in the prompt, the model no longer spends a call looking for it.

## What the measurement found that is not fixed

**Observation replaced reading, and the answer got worse.** `broken_page` seeds
a page with two defects: a price in white on white, and `textContnet` instead of
`textContent`. Reading the source found both. Calling `inspect_page` — the tool
choice the guidance was written to encourage — found **neither**, and answered
about missing structure and empty space instead. The typo is a silent no-op, so
it is not a console error, and the invisible price is invisible in rendered text
by construction. Looking is not a superset of reading, and the guidance now
reads as though it were.

This is exactly why the scenario was left as it was rather than rewritten to
match the behaviour: the automatic check says "ok" for the run whose answer is
worse.

**The artifact is still described without being seen.** `castle` writes the
file and then reports glowing windows and moving clouds, ending with "you can
open this file in any browser". No `inspect_page`, no steering. So 4.3's two
halves separated cleanly: making the thing is fixed, checking it before
describing it is not, and the second half is not a prompt problem — the same
prompt made `broken_page` inspect when the person asked it to look.

**The overlay is obeyed in part.** `AGENTS.md` said to answer in English and
start with "OK". The answer began with "OK." and continued in Russian. The "OK"
is unambiguous evidence that the overlay reached the model, was placed where the
model reads it, and changed the answer; the language shows a small model's
instinct to match the question beating a standing instruction. Mechanism
confirmed, compliance partial.

## Deployed

```text
modal deploy deploy/modal/control_app.py    App deployed in 8.051s
tools/telegram_profile.py --publish         menu now carries /agents
```

Only `assistant-control` was deployed; the model App was not deployed and no GPU
worker was started by either action. The first `modal deploy` attempt failed
printing a check mark to a cp1252 console — the image had already built — and
succeeded unchanged with `PYTHONUTF8=1`. Worth knowing on this machine; it is
not a property of the deployment.

`/agents` has not yet been used in the real Telegram chat. Everything above is
the same agent and the same code path, driven from the scenario runner rather
than from a phone.
