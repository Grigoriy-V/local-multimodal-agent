"""Offline checks on the Modal model endpoint definition.

`deploy/modal/` is infrastructure and nothing in `app/` imports it, so this is
not a test of product behaviour. It exists because the alternative way to
discover a mistake in the readiness loop or the deployment identity is a GPU
container, and that costs money and a human gate every time.

Two things are checked, and both are cheap:

- the readiness wait, whose three outcomes must each be distinguishable — a
  container that hangs silently or reports the wrong cause is exactly what step
  3b needs not to happen while measuring cold starts;
- the constants that keep this file from being deployed over the measured
  baseline App.

Nothing here starts a container, opens a socket or reads a credential.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "deploy" / "modal" / "model_app.py"

try:
    import modal  # noqa: F401 - presence is the condition, not the import
except ImportError:  # pragma: no cover - the deploy group is optional
    model_app = None
else:
    spec = importlib.util.spec_from_file_location("model_app_under_test", SOURCE)
    model_app = importlib.util.module_from_spec(spec)
    sys.modules["model_app_under_test"] = model_app
    spec.loader.exec_module(model_app)


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeRequestException(Exception):
    pass


class FakeRequests:
    """Stands in for the `requests` the container gets from `image.imports()`.

    Locally that import does not bind, so the module global is absent rather
    than real — which is what makes this substitution honest instead of a
    monkeypatch over a working library.
    """

    RequestException = FakeRequestException

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        # The last reply repeats rather than defaulting to healthy, so a test
        # about never becoming ready cannot pass by running out of script.
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeProcess:
    """A subprocess that is alive until it has been polled `dies_after` times."""

    def __init__(self, dies_after=None, returncode=1):
        self.polls = 0
        self.dies_after = dies_after
        self.returncode = returncode

    def poll(self):
        self.polls += 1
        if self.dies_after is not None and self.polls > self.dies_after:
            return self.returncode
        return None


@unittest.skipIf(model_app is None, "the deploy dependency group is not installed")
class WaitReadyTests(unittest.TestCase):
    def setUp(self):
        self.original_requests = getattr(model_app, "requests", None)
        self.original_interval = model_app.POLL_INTERVAL
        # Real polling would make every retry case take seconds.
        model_app.POLL_INTERVAL = 0.0

    def tearDown(self):
        model_app.POLL_INTERVAL = self.original_interval
        if self.original_requests is None:
            model_app.__dict__.pop("requests", None)
        else:
            model_app.requests = self.original_requests

    def use(self, replies):
        fake = FakeRequests(replies)
        model_app.requests = fake
        return fake

    def test_returns_elapsed_time_once_health_answers(self):
        fake = self.use([FakeResponse(200)])

        elapsed = model_app._wait_ready(FakeProcess(), timeout=10, stage="start")

        self.assertGreaterEqual(elapsed, 0.0)
        self.assertTrue(fake.calls[0].endswith("/health"))

    def test_keeps_waiting_through_refusals_and_unhealthy_replies(self):
        # A bound port that is not serving yet is the normal cold-start shape:
        # connection errors first, then 503 from a live server, then ready.
        fake = self.use(
            [
                FakeRequestException("connection refused"),
                FakeResponse(503),
                FakeResponse(200),
            ]
        )

        model_app._wait_ready(FakeProcess(), timeout=10, stage="start")

        self.assertEqual(len(fake.calls), 3)

    def test_reports_the_return_code_when_vllm_exits(self):
        self.use([FakeRequestException("connection refused")])
        process = FakeProcess(dies_after=1, returncode=3)

        with self.assertRaises(RuntimeError) as raised:
            model_app._wait_ready(process, timeout=10, stage="start")

        message = str(raised.exception)
        self.assertIn("start", message)
        self.assertIn("code 3", message)

    def test_reports_the_last_health_result_when_the_budget_expires(self):
        self.use([FakeResponse(503)])

        with self.assertRaises(RuntimeError) as raised:
            model_app._wait_ready(FakeProcess(), timeout=0, stage="resume")

        message = str(raised.exception)
        self.assertIn("resume", message)
        self.assertIn("503", message)
        self.assertIn("still running", message)

    def test_a_hung_server_cannot_wait_forever(self):
        # The failure this replaces: an unbounded loop that Modal eventually
        # kills on the function timeout with no indication of the cause. A
        # positive budget against a server that never becomes healthy is what
        # proves the deadline governs the loop rather than merely predating it.
        import time

        fake = self.use([FakeResponse(503)])

        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            model_app._wait_ready(FakeProcess(), timeout=0.05, stage="start")

        self.assertLess(time.monotonic() - started, 5.0)
        self.assertGreater(len(fake.calls), 1)


@unittest.skipIf(model_app is None, "the deploy dependency group is not installed")
class DeploymentIdentityTests(unittest.TestCase):
    def test_does_not_deploy_over_the_measured_baseline(self):
        self.assertNotEqual(model_app.APP_NAME, "assistant-llm")

    def test_scales_to_zero_with_an_explicit_ceiling(self):
        self.assertEqual(model_app.MIN_CONTAINERS, 0)
        self.assertEqual(model_app.MAX_CONTAINERS, 1)

    def test_the_idle_window_is_a_priced_choice_not_a_leftover(self):
        # Twelve seconds: long enough that an ordinary back-and-forth finds the
        # container warm, short enough to give up two thirds of the idle cost a
        # 30 s window carried. Still below the ~20 s a waiting approval needs,
        # which is the accepted pause. Changing it is a money decision, so it
        # should fail here and be re-argued rather than drift.
        self.assertEqual(model_app.SCALEDOWN_WINDOW, 12)
        self.assertLess(model_app.SCALEDOWN_WINDOW, 20)

    def test_the_whole_start_path_fits_under_what_modal_waits_for(self):
        # Not just each budget: their sum. Readiness alone was inside the
        # ceiling while readiness plus warmup plus sleep was double it, so a
        # per-timeout check passed while the container could still be killed
        # part way through reporting why it failed.
        worst_start = (
            model_app.START_READY_TIMEOUT
            + model_app.WARMUP_TIMEOUT * model_app.WARMUP_REQUESTS
            + model_app.SLEEP_TIMEOUT
        )
        self.assertLess(worst_start, model_app.STARTUP_TIMEOUT)

    def test_the_whole_resume_path_fits_too(self):
        worst_resume = model_app.SLEEP_TIMEOUT + model_app.WAKE_READY_TIMEOUT
        self.assertLess(worst_resume, model_app.STARTUP_TIMEOUT)

    def test_leaves_headroom_for_the_sleep_mode_allocator(self):
        # The first paid invocation died at cumem_allocator.cpp:163 because the
        # observed default of 0.92 sizes a KV cache the allocator cannot commit.
        # Anything at or above that reintroduces the OOM.
        self.assertLess(model_app.GPU_MEMORY_UTILIZATION, 0.92)

    def test_video_stays_unset_so_audio_is_never_the_profiled_modality(self):
        # The crash recorded in reports/2026-08-28_v2_step3a_model_endpoint.md.
        self.assertNotIn("video", model_app.MM_LIMITS)


QWEN_SOURCE = SOURCE.with_name("model_app_qwen.py")

if model_app is not None:
    # `model_app_qwen` imports its sibling by name, as Modal's CLI and the
    # container both allow; here the directory has to be on the path for it.
    sys.path.insert(0, str(SOURCE.parent))
    sys.modules["model_app"] = model_app
    spec = importlib.util.spec_from_file_location("model_app_qwen_under_test", QWEN_SOURCE)
    model_app_qwen = importlib.util.module_from_spec(spec)
    # A dataclass resolves its annotations through sys.modules; register
    # first, as importing would.
    sys.modules[spec.name] = model_app_qwen
    spec.loader.exec_module(model_app_qwen)
else:  # pragma: no cover
    model_app_qwen = None


@unittest.skipIf(model_app_qwen is None, "modal is not installed")
class SecondModelIdentityTests(unittest.TestCase):
    """The second App is its own identity and shares the first one's machinery."""

    def test_is_neither_the_baseline_nor_the_gemma_app(self):
        self.assertNotIn(model_app_qwen.APP_NAME, {"assistant-llm", model_app.APP_NAME})
        self.assertNotEqual(model_app_qwen.SERVED_NAME, model_app.SERVED_NAME)

    def test_the_card_holds_the_weights(self):
        # FP8 weights of a 27B model are ~26 GiB; nothing under 48 GB holds them
        # with a pool beside. The name is Modal's.
        self.assertEqual(model_app_qwen.GPU, "L40S")
        self.assertGreater(model_app_qwen.GPU_MEMORY_UTILIZATION, model_app.GPU_MEMORY_UTILIZATION)
        self.assertLessEqual(model_app_qwen.GPU_MEMORY_UTILIZATION, 0.90)

    def test_sleep_has_the_cpu_memory_the_weights_need(self):
        self.assertGreaterEqual(model_app_qwen.MEMORY_MB, 28 * 1024)

    def test_parsers_match_the_template(self):
        # What the model's own chat template requires: XML-shaped calls, and
        # a `<think>` block that must not reach the client as the answer.
        self.assertEqual(model_app_qwen.TOOL_CALL_PARSER, "qwen3_xml")
        self.assertEqual(model_app_qwen.REASONING_PARSER, "qwen3")
        self.assertIn("enable_thinking", model_app_qwen.DEFAULT_CHAT_TEMPLATE_KWARGS)

    def test_the_idle_window_and_timeouts_are_the_first_apps(self):
        # One priced choice, made once; the second App inherits it by import
        # rather than restating a number that would then drift.
        self.assertIs(model_app_qwen.base, model_app)

    def test_a_cold_compile_fits_the_start_path(self):
        # INT4 on the A100 spent 191 s compiling and was killed at 420 s.
        self.assertGreaterEqual(model_app_qwen.START_READY_TIMEOUT, 10 * 60)
        worst_start = (
            model_app_qwen.START_READY_TIMEOUT
            + model_app.WARMUP_TIMEOUT * model_app.WARMUP_REQUESTS
            + model_app.SLEEP_TIMEOUT
        )
        self.assertLess(worst_start, model_app_qwen.STARTUP_TIMEOUT)

    def test_no_ahead_of_time_compile(self):
        # The fourth INT4 boot died in `aot_compile_fullgraph`; nothing here
        # ever loads an AOT artifact, the snapshot holds the compiled engine.
        self.assertEqual(model_app_qwen.QWEN_ENV.get("VLLM_USE_AOT_COMPILE"), "0")

    def test_a_dry_boot_exists_for_every_qwen_app(self):
        # A configuration boots once in a Function that cannot loop before it
        # boots in the server that can.
        self.assertTrue(callable(model_app_qwen.dry_boot))
        self.assertIsNotNone(getattr(model_app_qwen, "dry_run", None))
        self.assertIsNotNone(getattr(model_app_qwen_int4, "dry_run", None))

    def test_the_snapshot_holds_nothing_on_the_compile_cache_volume(self):
        # ISS-0047: the Qwen Apps' boot neither reads nor commits the
        # compile-cache Volume; the source is the record of that.
        import inspect

        source = inspect.getsource(model_app_qwen.boot)
        self.assertNotIn("vllm_cache", source)
        self.assertNotIn("copy_tree", source)

    def test_the_qwen_apps_run_their_own_vllm_pair(self):
        # 0.28.0 turns prefix caching on for hybrid models by default; the
        # Gemma App keeps the pair validated with it.
        self.assertNotEqual(model_app_qwen.VLLM_VERSION, model_app.VLLM_VERSION)
        self.assertEqual(model_app_qwen.VLLM_VERSION, "0.28.0")
        self.assertEqual(model_app_qwen.TRANSFORMERS_VERSION, "5.15.0")
        self.assertEqual(model_app.VLLM_VERSION, "0.26.0")

    def test_prefix_caching_is_asked_for_and_thinking_is_off_by_default(self):
        command = model_app_qwen.serve_command(model_app_qwen.SERVING)
        self.assertIn("--enable-prefix-caching", command)
        self.assertEqual(model_app_qwen.DEFAULT_CHAT_TEMPLATE_KWARGS, {"enable_thinking": False})

    def test_the_command_is_the_spec(self):
        command = model_app_qwen.serve_command(model_app_qwen.SERVING)
        self.assertEqual(command[:3], ["vllm", "serve", model_app_qwen.MODEL_REPO])
        self.assertIn("--max-num-seqs", command)
        self.assertEqual(command[command.index("--tool-call-parser") + 1], "qwen3_xml")
        self.assertEqual(command[command.index("--reasoning-parser") + 1], "qwen3")
        self.assertIn("--enable-sleep-mode", command)


@unittest.skipIf(model_app_qwen is None, "modal is not installed")
class PoolArithmeticTests(unittest.TestCase):
    """`fits` reproduces the boots of 2026-09-05 before any GPU is paid for."""

    FP8_ON_DISK = 28.75

    def test_the_first_fp8_boot_is_refused_by_the_arithmetic(self):
        # 0.86 at 131,072: 7.04 GiB of KV against 8.18 needed, refused by vLLM.
        spec = model_app_qwen.Serving(
            repo="r", revision="v", served_name="s", gpu="L40S", card_gib=44.39,
            max_model_len=131072, utilization=0.86,
        )
        ok, line = model_app_qwen.fits(spec, self.FP8_ON_DISK)
        self.assertFalse(ok, line)

    def test_the_served_fp8_boot_passes(self):
        # 0.90 at 131,072 served with 9.75 GiB of KV; the estimate must not
        # refuse a configuration that booted.
        ok, line = model_app_qwen.fits(model_app_qwen.SERVING, self.FP8_ON_DISK)
        self.assertTrue(ok, line)

    def test_kv_per_token_is_the_measured_one(self):
        # vLLM: 8.18 GiB for 131,072 tokens.
        self.assertAlmostEqual(model_app_qwen.kv_gib(131072), 8.0, places=1)


INT4_SOURCE = SOURCE.with_name("model_app_qwen_int4.py")

if model_app_qwen is not None:
    sys.modules["model_app_qwen"] = model_app_qwen
    spec = importlib.util.spec_from_file_location("model_app_qwen_int4_under_test", INT4_SOURCE)
    model_app_qwen_int4 = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = model_app_qwen_int4
    spec.loader.exec_module(model_app_qwen_int4)
else:  # pragma: no cover
    model_app_qwen_int4 = None


@unittest.skipIf(model_app_qwen_int4 is None, "modal is not installed")
class ThirdModelIdentityTests(unittest.TestCase):
    INT4_ON_DISK = 18.14 * 1e9 / 1024**3

    def test_is_its_own_app_and_name(self):
        names = {"assistant-llm", model_app.APP_NAME, model_app_qwen.APP_NAME}
        self.assertNotIn(model_app_qwen_int4.APP_NAME, names)
        self.assertNotEqual(model_app_qwen_int4.SERVED_NAME, model_app_qwen.SERVED_NAME)

    def test_the_card_and_the_pool(self):
        self.assertEqual(model_app_qwen_int4.GPU, "A100-40GB")
        ok, line = model_app_qwen.fits(model_app_qwen_int4.SERVING, self.INT4_ON_DISK)
        self.assertTrue(ok, line)

    def test_sleep_has_the_cpu_memory_the_weights_need(self):
        self.assertGreaterEqual(model_app_qwen_int4.MEMORY_MB, 20 * 1024)

    def test_shares_the_qwen_machinery(self):
        self.assertIs(model_app_qwen_int4.qwen, model_app_qwen)
        self.assertEqual(model_app_qwen_int4.SERVING.tool_call_parser, "qwen3_xml")
        self.assertEqual(model_app_qwen_int4.SERVING.max_num_seqs, model_app_qwen.MAX_NUM_SEQS)


if __name__ == "__main__":
    unittest.main()
