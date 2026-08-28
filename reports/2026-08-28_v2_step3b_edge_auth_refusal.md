# V2 step 3b — unauthenticated requests are refused at the Modal edge

**Date:** 2026-08-28
**Agent:** claude
**Outcome:** passed. No container was started and no GPU time was billed.

## Why this was tested

The endpoint URL appears in pushed commits, documentation and reports, and the
GitHub repository is public. The URL is not and cannot be a secret: Modal
derives it deterministically as `<workspace>--<app>-<class>-<method>.modal.run`,
so anyone who knows the workspace name can construct it without this repository.
The only defence that matters is `requires_proxy_auth=True`.

That defence had been measured on the baseline `assistant-llm` during step 3a,
but never on `assistant-llm-v2`, which uses a different decorator
(`@modal.web_server` rather than `app.server()`). Acceptance for the baseline
does not transfer. With the URL public, the untested property was whether an
unauthenticated request is rejected at the edge or is allowed to wake a paid A10.

## Measurement

`modal container list --json` returned `[]` immediately before and immediately
after the three requests below, all sent to
`https://grigoriy-v--assistant-llm-v2-server-serve.modal.run/v1/models` with
redirects followed.

| Credential | Status | Time |
|---|---|---|
| none | **401** | 0.72 s |
| invalid joined bearer token | **401** | 1.14 s |
| invalid `Modal-Key` / `Modal-Secret` pair | **401** | 0.62 s |

All three were refused in under 1.2 seconds — the edge-rejection latency, far
below the roughly 10 s of a snapshot restore. An invalid credential is refused
exactly like a missing one, so a wrong token cannot be used to wake the worker
either.

## Conclusion

Publishing the URL grants no access and cannot be used to spend the owner's
compute. Exposure in commits and documentation is accepted as low risk for this
deployment, and the URL may continue to appear in evidence and command examples.

This result is specific to the current `assistant-llm-v2` Function revision. If
`requires_proxy_auth` or the web decorator changes, the check must be repeated;
it costs nothing.

Separately verified while answering the same question: `.env` is untracked and
covered by `.gitignore`, and no real `wk-`/`ws-` token exists in any tracked file
or anywhere in Git history — only placeholders.
