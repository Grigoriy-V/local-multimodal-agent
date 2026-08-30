# Two Telegram albums, eight turns — what a media group does to this design

**Date:** 2026-08-30
**Agent:** Claude, direct session
**Outcome:** diagnosed from the deployed record. One defect fixed here; the
larger one is written up and not begun.

## What the person did, and what they expected

Two albums of four documents each were sent to the bot — an upload the Telegram
client would not let them cancel, which then lagged. The expectation was the
obvious one: four documents in one message is one request, so the assistant
reads them, or asks what to do with them, and answers once.

## What actually happened

Telegram does not send an album as one message. It sends one `message` update
per item, sharing a `media_group_id`, and only one of them carries the caption.
The record shows the two albums arriving as eight updates about 1.2 s apart:

```text
02:39:10.163  814912968  spawning: true
02:39:11.387  814912969  spawning: true
02:39:12.605  814912970  spawning: true
02:39:13.826  814912971  spawning: true
02:39:15.046  814912972  spawning: true
02:39:16.295  814912973  spawning: true
02:39:17.528  814912974  spawning: true
02:39:18.752  814912975  spawning: true
```

`media_group_id` appears nowhere in this repository. `read_update` in
`ui/telegram/wire.py` reads `message.get("document")` — one document — so there
is nothing that could join them. Eight updates became eight queued rows, eight
requests for a worker, and eight turns.

The turns ran one after another, because a lease belongs to a conversation:
02:39:29, 02:39:53, 02:40:18, 02:40:51, 02:41:22, 02:41:31, 02:42:52, 02:43:19.
Each spent two model calls and one `read_document`. Each appended its document
to the same thread, so the context grew as it went — 19,971, then 27,549, then
34,337 input tokens.

Three of the eight failed: `BackendError`, `RemoteProtocolError`, and one
`incomplete`, which is the signature of the container the person killed by hand
while trying to stop it.

Across the nine turns in that window: **$0.0864 derived, about 47 s of GPU per
successful turn.** Not an expensive accident. It is eight turns of work, and
eight answers, where one was wanted.

## Two separate faults

**The spawn storm.** Every one of the eight updates asked Modal for a worker.
Seven of those workers could not have done anything: `_claim_conversation`
refuses while another holds the conversation's lease, so they started, claimed
nothing and exited. The queue was already correct — 4.0 made sure a burst is
answered in order by one warm container — but the front door was still asking
for a container per message.

**The album itself.** Even with one container, four documents produced four
turns and four answers, and three of the four arrived with no text at all,
because Telegram put the caption on one of them.

## What was fixed here

Only the first. `PostgresUpdateInbox.enqueue` now asks whether the conversation
already has a running row with a live lease, and suppresses the spawn when it
does. The row is still queued — what is suppressed is the container, never the
message — and the worker holding the lease drains it.

The lease has to be *live*, not merely `running`. A running row with an expired
lease is what a dead container leaves behind, and that is precisely the case
that needs a new worker started. Control updates never take this path: `/stop`
waiting for the turn it is about is the flaw the out-of-band lane exists to
prevent.

Five contracts were added to `tests/test_update_inbox_contract.py`, which runs
against PostgreSQL itself: the suppression, the dead-worker exception, another
person not being held up, control updates always spawning, and rows queued
before the conversation key existed still spawning. 21 passed live against the
deployed database.

This changes what is started, never what is answered. The same messages are
queued and drained in the same order.

## What was not fixed

Coalescing the album. It is not a small change and it should not be pretended
into one:

- the turn's identity is created at the front door, one per update, and every
  recorded number counts turns that way — this is the reason 4.0 explicitly
  held coalescing back;
- an album has no end marker. The only way to know it is complete is to wait a
  short time after the last item, which means holding a message before
  answering it — a deliberate delay in the product's most sensitive path;
- the caption arrives on one arbitrary item, so the text and the files have to
  be joined across updates before either is useful;
- the deployed profile has no process that lives between updates. The waiting
  would have to happen in the queue or in a worker that deliberately lingers.

None of that is a reason to leave it undone. It is a reason to design it rather
than patch it. Recorded in `ROADMAP.md` under "Not started".

## What this says about the assistant's own behaviour

Worth separating from the plumbing: even had the four documents arrived as one
turn, the right answer is probably not to read all four. The person's stated
expectation was that it would read them **or ask what to do with them**. That is
a decision for the loop, and it is the kind of thing 4.5's `ask_user` exists
for. A turn handed four documents and no instruction has a genuinely missing
decision, not a permission to request.

## A correction carried from the same session

An earlier claim in `reports/2026-08-30_v2_context_capacity.md` — that a turn
whose delivery failed would be re-run from the beginning, model calls included —
was wrong, and this incident's record is what disproved it. When the failed
update was reclaimed at 02:39:15 it finished `answer_delivered` with **0 model
calls and 0 tokens**: the checkpointer held the completed graph and the resume
delivered the answer that already existed. The cost of a failed delivery is the
delay, not the work.
