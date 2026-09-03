# 4.6b: exact recovery from archived history — review before building

Date: 2026-09-03. Direct Claude session. Nothing here is approved; the
roadmap carries 4.6b as the next item in order, and selecting it is the
human's word. Options are written as options.

## 1. What 4.6b promises

`ROADMAP.md`: *a search over what was actually said, returning real messages
and tool results rather than another summary, so a detail a summary lost is
recoverable. Full-text in both profiles; it joins the `ConversationStore`
contract suite. No vector store.*

The decision it rests on, `DECISIONS.md` 2026-08-30 "Stored history is
canonical": a summary is safe to be wrong only because *the exact wording,
error or filename is still recoverable from what was actually said*. Today
that recovery exists on paper. Nothing in the running product can reach a
message behind the summary; the model's only way back to an old tool result
is the stub's "call the tool again", which re-runs a fetch or a render for
text that already sits in the store.

## 2. What is in the tree that 4.6b reads

- `messages(thread_id, position, role, content, tool_calls, tool_call_id,
  failure, created_at)`, identical in SQLite and Postgres; `content` is a JSON
  list of parts with **base64 media inline**. Neon holds 854 rows.
- `compactions(thread_id, through, folded, trigger, summary_chars)` — one row
  per fold, so "what does this summary stand for" is answerable as a position
  range: the summary covers `1..through`.
- Facts already have full-text search in both profiles: FTS5 with an external
  content table and triggers locally, a `simple` (unstemmed) generated
  `tsvector` with a GIN index on Neon, one sanitised query builder each
  (`match_query`), `bm25`/`ts_rank` ordering. The contract suite covers it.
- The stub on the surface: `[fetch_page https://…: 12000 characters;
  shortened, call the tool again for the full result]`. It names the tool and
  an argument, not a place in history.
- The tool result stored is the **capped** one: `bounded()` in
  `app/tools/execution.py` cuts a result to 32k characters with head, marker
  and tail *before* it enters the conversation, and that is the row. The
  omitted middle of a result over 32k is not in history. Same for images past
  the count and byte caps. "The full result in history" is true up to that
  backstop and nowhere past it.

## 3. What the references do

Shapes, not endorsements. The three harnesses of
`reports/2026-09-03_v2_tool_system_references_and_queue.md`, plus Anthropic's
API. Where I state a detail from memory rather than from that report, it is
marked *(recalled)* and is to be checked before anyone builds on it.

| Concern | Reference shape | Ours today |
|---|---|---|
| Where the full text lives after pruning | DeepSeek: a spill store keyed by locator, the pruned result carries a `retrievalHint`. Hermes: `cache/spillover/<id>.txt` with a preview. OpenClaw: the session transcript file survives compaction. | The store row, capped at 32k; no locator on the stub |
| How the model gets it back | DeepSeek: a read by locator. Hermes *(recalled)*: a `session_search` tool over past transcripts in FTS5, results condensed before they reach the model. OpenClaw *(recalled)*: `memory_search` over memory files, hybrid BM25 + vectors, optional. Claude Code, Codex CLI: no search tool over past turns; the summary plus the files on disk are the recovery. Anthropic API: context editing clears old tool results to a placeholder and offers no read-back; the memory tool is a directory the model reads and writes. | Nothing; "call the tool again" |
| What the placeholder says | DeepSeek: what was cut and how to get it. Anthropic: a fixed placeholder. | Tool, argument, size, "call again" |
| Scope of the search | Hermes, OpenClaw: across sessions. Claude Code `/resume`: a whole past session, chosen by the person. | Facts: per user, across conversations |
| Ranking | BM25 everywhere text is searched; vectors only in OpenClaw's hybrid and only as an option. | BM25 / `ts_rank` on facts |
| Condensing hits | Hermes *(recalled)* runs a cheap model over hits. Others return text. | — |

Three of these do **not** fit here:

- **A spill store.** History is canonical and already durable in both
  profiles; a second copy on disk is a second source of truth, which
  `DECISIONS.md` 2026-08-30 rules out. What a spill store has that we lack is
  the uncapped result, and that is a question about the 32k backstop (§6), not
  about where to put a file.
- **Vectors.** `DECISIONS.md` 2026-08-01: text retrieval first, measured. The
  question 4.6b answers is "the exact filename, error, number"; that is a
  keyword search by nature, and BM25 over the person's own words is the right
  tool for it. A summary already stands in for the fuzzy case.
- **A condensing model over the hits.** The point of 4.6b is *not another
  summary*. Hits are returned as they were said, bounded by the existing
  per-result cap. If a hit is long, the model reads it; that is the capability.

## 4. The design, as small as it stays whole

**One column, one index, two tools, one locator.**

**Column.** `messages.text`: the concatenated text parts of `content`,
written at `append` and backfilled once for existing rows. Not an expression
over `content`, because `content` carries base64 media and a tsvector over
it would index image bytes; and not a Postgres-only generated column,
because the SQLite side needs the same plain text for its FTS5 content
table. `opening_text()` in `app/memory/records.py` already computes this for
the thread list; it becomes the one definition.

**Index.** SQLite: `messages_fts` as FTS5 over `text` with
`content='messages'`, the same trigger pattern `facts_fts` uses. Postgres: a
generated `tsvector` in `simple` on `text`, GIN. The same `match_query`
builders. Ranking: `bm25` / `ts_rank`, then newest first. Both are schema
**4**, one migration, one gate: the backfill touches every existing row on
Neon (854 today), and `tools/setup_control_plane.py` runs it as it ran 3.

**Tool 1, `search_history(query, all_conversations=false)`.** Returns up to
N hits (N = 8 as a start) as they were said: `#<position>` in
`<conversation>`, `<role>`, `<created_at>`, and the text, each hit cut to a
few hundred characters around the first match so the result is a page, not a
transcript. Current conversation by default; the person's other conversations
on request, never another user's — the same `user_id` fence as facts.
Failures are searchable too: `failure` is a JSON column and the error message
is exactly the detail a summary drops, so the text column includes it.

**Tool 2, `read_history(position, count=1, conversation=current)`.** The
whole stored message(s) at a position, through the same `post_execute`
backstop as any result. This is what turns a hit into the exact wording, and
it is what the stub points at.

**Locator.** The stub gains the position:
`[fetch_page https://…: 12000 characters; shortened — read_history 41 for
it, or call the tool again for a fresh one]`. Exact recovery for the price
of one integer, and the model stops re-running a 30 s fetch to re-read text
it already had. This is DeepSeek's `retrievalHint` with history as the store.

**Prelude.** One sentence after the summary, only when there is one:
*"Details from before this summary can be found with search_history."* The
summary instruction is unchanged; the model is told where the exact words
are rather than asked to keep more of them.

**Compactions.** Read by `read_history` for the range a summary covers and
by `/context`, which can now say "summary covers messages 1–120". No new
model-facing tool for it: a range is enough.

Nothing else. No change to folding, stubbing or the surface order; those are
4.6a's and are measured.

## 5. What 4.6b should not become

- No spill files, no vectors, no second model, no rewriting of history.
- No automatic injection of search hits into the prompt. The model asks;
  that keeps the prefix stable (4.6a's cache work) and keeps recall a
  decision the trace can show, the same rule as `remember_fact`.
- No search across users, under any flag.
- No "importance" ranking. Match, then recency, explained in one sentence.

## 6. The one thing to decide beyond the plan

The 32k backstop caps what the store keeps. Two options:

- **A. Keep the cap as it is.** History is exact up to 32k per result, which
  is every result seen in the live tests so far. Cheapest; 4.6b recovers what
  the model saw, which is what the decision literally promises.
- **B. Store the uncapped result, show the capped one.** `bounded()` moves
  from before the store to the surface, like `shortened`. Exact recovery of
  anything ever returned, at the cost of unbounded rows (a 2 MB page) in a
  store that is re-read every turn by `messages()`, so it needs a limit of its
  own and a reason for it.

Recommendation: **A**, and record it, so the sentence "the full result stays
in history" reads with its cap. If a live case ever needs the middle of a
result over 32k, that is the evidence for B.

## 7. Order of work, if approved

1. `text` column and both indexes, `search_history`/`read_history` on the
   `ConversationStore` contract with the suite's tests: hits ranked, other
   users invisible, failures found by their message, a hit beyond a
   compaction found. Schema 4 on the local profile. No gate.
2. The two tools, the locator in the stub, the prelude sentence. Offline
   tests on the projection.
3. **Gate:** the Neon migration to schema 4.
4. Deploy; `/check` and `loop_live.py --after-deploy` (rule).
5. Live, with permission: a folded conversation from today (the 26-message
   tool turn of `4fd35f80` is a good one), asked for the exact error text
   from before the summary; and a turn whose old result was stubbed, where
   the model should read it back by position rather than fetch again. Both
   read through `tools/show_run.py`; one `ml_work` record with hit rank and
   the calls saved.

## 8. Cost and size

Two store methods, two tools, one column, one migration, a sentence in the
prelude and an integer in the stub. Contract tests in the existing suite.
The Neon backfill is milliseconds at 854 rows. No new service, no new model,
no GPU beyond the two live turns of step 5.
