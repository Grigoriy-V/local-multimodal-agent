# Version 1.5 product acceptance

**Date:** 2026-08-02  
**Result:** closed

## Delivered engineering

Version 1.5 turns the persistent multimodal chat baseline into a general local
autonomous harness:

- every ordinary request enters one natural-language route; the model chooses a
  direct answer or autonomous work without a UI mode or per-tool button;
- work follows `plan -> approve -> implement -> validate/evaluate ->
  repair/finalize` with bounded iterations and tool calls;
- plans bind task-specific criteria to model-selected filesystem or browser
  evidence, and evaluation consumes the collected tool results;
- the capability registry enforces workspace scope and explicit grants while
  keeping tool choice inside the harness;
- browser inspection returns rendered text, console state and screenshots;
- `read_file`, `write_file` and `edit_file` accept relative paths and absolute
  paths that resolve inside the configured workspace;
- task checkpoints support approval, restart and durable cancellation;
- Chainlit shows plans, scope, progress, checks, evidence and downloadable
  artifacts while remaining a replaceable adapter;
- native conversation deletion removes canonical messages and both resumable
  checkpoint identities without deleting separately approved account memory.

Production control flow contains no Snake-specific verifier or manual
`task`/`preview` workflow. Snake is only an acceptance scenario for the general
harness.

## Product evidence

The human performed the final visual check through the actual application.

| Evidence | What it demonstrates |
|---|---|
| [`1.png`](test_v1.5/1.png) | The initial Snake request produced a downloadable `index.html`, then stopped honestly when validation crossed the model's context ceiling. |
| [`2.png`](test_v1.5/2.png) | A normal follow-up request completed after 3 iterations and 18 tool calls; all 3 criteria passed using browser evidence, and the artifact remained downloadable. |
| [`3.png`](test_v1.5/3.png) | The same entry point still handles an ordinary conversational request directly. |
| [`4.png`](test_v1.5/4.png) | Manual play reached score 30, collision, `Game Over` and the `Play Again` control. |
| [`5.png`](test_v1.5/5.png) | The running artifact visibly contains the requested blue Snake and red food. |

The materially different HTML task, native stop, restart persistence and chat
deletion were already exercised through the actual UI in
[`2026-08-02_v15_step5_chainlit_product_surface.md`](2026-08-02_v15_step5_chainlit_product_surface.md).

## Known limitation

The first final run exposed a real boundary condition: with a 16,384-token model
ceiling, at least 12,289 input tokens plus a requested 4,096 output tokens exceed
the limit by one token. The harness reported `stopped` and preserved the created
artifact instead of claiming successful validation. A follow-up task recovered
and completed, but context/output-budget tuning remains later work.

This does not block the Version 1.5 baseline: direct conversation, autonomous
planning and action, bounded repair, model-selected validation, browser
evidence, manual artifact use and honest failure reporting are demonstrated.

## Verification basis

- Last full offline regression after the Version 1.5 implementation:
  `321 passed in 7.62s`.
- Step 5 included restart/persistence, active cancellation, artifact rendering
  and native deletion checks against the real application and SQLite files.
- Final visual acceptance: supplied by the human in `reports/test_v1.5/`.
- No model, browser or full test suite was rerun during this documentation-only
  finalization, by explicit request.

No external provider call or monetary cost was incurred during finalization.
