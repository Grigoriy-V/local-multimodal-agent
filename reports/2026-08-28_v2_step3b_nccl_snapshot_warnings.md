# V2 step 3b — NCCL warnings after GPU snapshot restore

**Date:** 2026-08-28  
**Agent:** Codex  
**Outcome:** read-only diagnosis complete; no deployment or worker invocation

## Observed behaviour

The optimized single-A10 deployment restores and serves correctly:

- `world_size=1`, rank 0, backend NCCL;
- the final control restored in 10.4 seconds;
- `resume: healthy after 0.0s`;
- text, image and audio have all passed on the audio-capable image;
- scale-to-zero works.

After GPU snapshot restore, however, PyTorch prints the following pair roughly
once per second until shutdown:

```text
TCPStore.cpp: sendBytes failed ... Broken pipe
ProcessGroupNCCL::HeartbeatMonitor::runLoop():
Failed to check the "should dump" flag on TCPStore
```

The warning starts around restore, continues while successful requests are
served, and stops only when the container shuts down. It is therefore not a
request failure and not evidence that the model is unhealthy.

## Diagnosis

vLLM creates a PyTorch distributed process group even for this one-GPU server.
Its startup log records a `tcp://172.20.x.x:<port>` distributed initialization
address. That process group, its NCCL heartbeat monitor and its TCPStore client
are all created before Modal captures the GPU snapshot.

On restore, the container has a new worker/network identity. The vLLM process
and heartbeat thread resume from the captured memory, but the TCPStore socket
they retained no longer has a live peer. The monitor then polls the stale socket
every second and emits `Broken pipe`. Inference still works because this is
`world_size=1`: there are no real cross-rank collectives that depend on that
connection.

This is an inference from the exact timing and upstream behaviour, not a Modal
root-cause statement. It is strongly supported by:

- PyTorch issue
  [#170290](https://github.com/pytorch/pytorch/issues/170290), which reproduces
  the same `Failed to check the "should dump" flag on TCPStore` storm when the
  TCPStore owner exits before the NCCL heartbeat monitor;
- the vLLM snapshot
  [RFC #52125](https://github.com/vllm-project/vllm/issues/52125), which names
  instance IP, `VLLM_HOST_IP`, `distributed_init_method` and NCCL network state
  as state that must be corrected when restoring an engine on a new instance;
- vLLM's official troubleshooting guide, which documents
  `VLLM_HOST_IP`, `NCCL_SOCKET_IFNAME` and `GLOO_SOCKET_IFNAME` as controls for
  the address/interface used by distributed initialization;
- Modal's memory-snapshot guide, which marks GPU snapshots Alpha and warns that
  complex inference engines may need snapshot-specific adaptation.

The preceding failed container is not attributed to this warning. The retained
CLI logs have no fatal traceback proving that relationship, and the same warning
appears throughout a fully successful 10.4-second restore.

## Fix order

No change is authorized yet. If the human chooses to fix the log spam, test one
variable at a time under a new deployment/snapshot identity.

### 1. Preserve the monitor; stabilize the internal address

First set the internal single-node rendezvous to loopback before vLLM starts:

```text
VLLM_HOST_IP=127.0.0.1
NCCL_SOCKET_IFNAME=lo
GLOO_SOCKET_IFNAME=lo
```

`VLLM_HOST_IP` is the important variable: vLLM uses it to choose the address in
`distributed_init_method`. The interface variables make the single-node intent
explicit. This keeps PyTorch monitoring enabled and attacks the stale
worker-address cause, but it remains an unverified snapshot experiment.

### 2. If loopback does not help, disable the irrelevant monitor

For this exact `world_size=1` deployment:

```text
TORCH_NCCL_ENABLE_MONITORING=0
```

PyTorch documents this variable as controlling the monitoring thread that
aborts a process when its watchdog heartbeat stalls. Disabling it should remove
the thread producing the warnings, but it also removes that deadlock protection.
The trade-off is small for a one-GPU, 30-second-idle service and becomes
unacceptable without reconsideration if tensor/data/pipeline parallelism is
introduced later.

Changing only `TORCH_NCCL_HEARTBEAT_TIMEOUT_SEC` is not a log-spam fix: the
observed message is the monitor's one-second TCPStore coordination check, not a
heartbeat timeout event. Increasing NCCL debug verbosity would add noise rather
than answer the already localized question.

## Decision

Leave the currently working deployment untouched. The warnings are noisy but
did not affect correctness, 10.4-second restore latency or scale-to-zero.

On 2026-08-28 the human explicitly rejected any warning-only fix that would
create another GPU snapshot. That excludes both proposed environment changes:

- the loopback variables must be present before vLLM creates its distributed
  process group;
- `TORCH_NCCL_ENABLE_MONITORING=0` is also read while
  `ProcessGroupNCCL` is constructed. Setting it after restore cannot remove the
  monitoring thread already captured in the current snapshot;
- adding either configuration to `modal.Image.env(...)` changes the deployed
  Function revision. Modal snapshots belong to deployed Functions, so that
  revision would have to build and validate its own GPU snapshot.

Therefore **no environment variable, deploy or worker invocation was made**.
The existing snapshot and working endpoint remain unchanged. The warnings are
accepted for the current revision. At the next deploy required for another
product change, apply the loopback rendezvous configuration before snapshot
creation and include the warning check in that deploy's ordinary acceptance;
do not rebuild a snapshot solely to clean the logs.

If `TORCH_NCCL_ENABLE_MONITORING=0` is reconsidered during a future rebuild,
record it as an explicit single-GPU deployment trade-off: it is expected to
remove this monitoring-thread log loop, but it also prevents PyTorch from
aborting the process when the NCCL watchdog stops producing heartbeats. That
can leave a genuinely hung distributed job alive longer, and the choice must be
revisited before tensor, data or pipeline parallelism, multiple GPUs, or longer
container lifetimes are introduced.

## Sources

- [Modal: Memory Snapshots](https://modal.com/docs/guide/memory-snapshots)
- [Modal: low-latency vLLM with snapshots](https://modal.com/docs/examples/lfm_snapshot)
- [PyTorch: ProcessGroupNCCL environment variables](https://docs.pytorch.org/docs/stable/torch_nccl_environment_variables.html)
- [PyTorch issue #170290](https://github.com/pytorch/pytorch/issues/170290)
- [vLLM snapshot RFC #52125](https://github.com/vllm-project/vllm/issues/52125)
- [vLLM troubleshooting](https://github.com/vllm-project/vllm/blob/main/docs/usage/troubleshooting.md)
