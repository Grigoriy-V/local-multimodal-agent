"""Reading the engine's own counters, without an engine.

Offline by construction: the parsing, the discovery of which names this vLLM
publishes, the refusal to subtract across a restart and the arithmetic are all
pure. Only the probe script touches the network, and running it wakes a GPU.
"""

from __future__ import annotations

from app.telemetry.vllm import (
    Measurement,
    Snapshot,
    delta,
    discover,
    missing,
    parse_metrics,
    render_discovery,
    restarted,
    summarize,
)

MODEL = 'model_name="gemma-4-12b-it"'

SAMPLE = f"""
# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{{{MODEL}}} 0.0
# TYPE vllm:prompt_tokens_total counter
vllm:prompt_tokens_total{{{MODEL}}} 1420.0
# TYPE vllm:generation_tokens_total counter
vllm:generation_tokens_total{{{MODEL}}} 18.0
# TYPE vllm:time_to_first_token_seconds histogram
vllm:time_to_first_token_seconds_bucket{{le="0.1",{MODEL}}} 0.0
vllm:time_to_first_token_seconds_bucket{{le="+Inf",{MODEL}}} 1.0
vllm:time_to_first_token_seconds_sum{{{MODEL}}} 0.140
vllm:time_to_first_token_seconds_count{{{MODEL}}} 1.0
# TYPE vllm:gpu_prefix_cache_queries counter
vllm:gpu_prefix_cache_queries{{{MODEL}}} 1024.0
# TYPE vllm:gpu_prefix_cache_hits counter
vllm:gpu_prefix_cache_hits{{{MODEL}}} 0.0
process_start_time_seconds 1.7e9
"""


def after_one_request() -> str:
    return SAMPLE.replace("vllm:prompt_tokens_total{" + MODEL + "} 1420.0",
                          "vllm:prompt_tokens_total{" + MODEL + "} 5420.0").replace(
        "vllm:generation_tokens_total{" + MODEL + "} 18.0",
        "vllm:generation_tokens_total{" + MODEL + "} 82.0",
    ).replace(
        "vllm:time_to_first_token_seconds_sum{" + MODEL + "} 0.140",
        "vllm:time_to_first_token_seconds_sum{" + MODEL + "} 0.640",
    ).replace(
        "vllm:time_to_first_token_seconds_count{" + MODEL + "} 1.0",
        "vllm:time_to_first_token_seconds_count{" + MODEL + "} 2.0",
    ).replace(
        "vllm:gpu_prefix_cache_queries{" + MODEL + "} 1024.0",
        "vllm:gpu_prefix_cache_queries{" + MODEL + "} 5120.0",
    ).replace(
        "vllm:gpu_prefix_cache_hits{" + MODEL + "} 0.0",
        "vllm:gpu_prefix_cache_hits{" + MODEL + "} 3072.0",
    )


# --- parsing -----------------------------------------------------------------


def test_counters_and_histogram_parts_are_read() -> None:
    snapshot = parse_metrics(SAMPLE)

    assert snapshot.values["vllm:prompt_tokens_total"] == 1420.0
    assert snapshot.values["vllm:time_to_first_token_seconds_sum"] == 0.140
    assert snapshot.values["vllm:time_to_first_token_seconds_count"] == 1.0
    assert snapshot.process_start == 1.7e9


def test_bucket_lines_are_dropped() -> None:
    """Summing `le` buckets would produce a number that means nothing."""

    snapshot = parse_metrics(SAMPLE)

    assert not any(name.endswith("_bucket") for name in snapshot.values)


def test_label_sets_are_summed_into_one_series() -> None:
    text = (
        "# TYPE vllm:prompt_tokens_total counter\n"
        'vllm:prompt_tokens_total{model_name="a"} 100.0\n'
        'vllm:prompt_tokens_total{model_name="b"} 25.0\n'
    )

    assert parse_metrics(text).values["vllm:prompt_tokens_total"] == 125.0


def test_the_families_the_engine_exposes_are_listed() -> None:
    snapshot = parse_metrics(SAMPLE)

    assert "vllm:time_to_first_token_seconds" in snapshot.families
    assert "vllm:num_requests_running" in snapshot.families


# --- discovery ---------------------------------------------------------------


def test_a_concept_is_matched_to_whichever_name_this_version_uses() -> None:
    """Names move between releases; the task document forbids copying them."""

    found = discover(parse_metrics(SAMPLE))

    assert found["prefix_cache_queries"] == "vllm:gpu_prefix_cache_queries"
    assert found["time_to_first_token"] == "vllm:time_to_first_token_seconds"
    assert missing(found) == ()


def test_a_counter_this_engine_does_not_publish_is_reported_missing() -> None:
    """It must read as absent, never as a zero somebody could quote."""

    without_cache = "\n".join(
        line for line in SAMPLE.splitlines() if "prefix_cache" not in line
    )

    found = discover(parse_metrics(without_cache))

    assert found["prefix_cache_hits"] is None
    assert set(missing(found)) == {"prefix_cache_queries", "prefix_cache_hits"}
    assert "NOT PUBLISHED" in render_discovery(parse_metrics(without_cache), found)


# --- restarts ----------------------------------------------------------------


def test_a_delta_across_a_restart_is_refused() -> None:
    """These counters belong to one container and reset when it comes back."""

    before = parse_metrics(after_one_request())
    after = parse_metrics(SAMPLE)

    assert restarted(before, after) is True


def test_a_new_process_with_higher_counters_is_still_a_restart() -> None:
    before = parse_metrics(SAMPLE)
    after = parse_metrics(after_one_request().replace("1.7e9", "1.8e9"))

    assert restarted(before, after) is True


def test_two_readings_of_one_engine_are_comparable() -> None:
    assert restarted(parse_metrics(SAMPLE), parse_metrics(after_one_request())) is False


# --- arithmetic --------------------------------------------------------------


def test_only_what_changed_appears_in_the_delta() -> None:
    changed = delta(parse_metrics(SAMPLE), parse_metrics(after_one_request()))

    assert changed["vllm:prompt_tokens_total"] == 4000.0
    assert "vllm:num_requests_running" not in changed


def test_one_request_is_summarized_from_the_delta() -> None:
    before, after = parse_metrics(SAMPLE), parse_metrics(after_one_request())
    found = discover(after)

    measured = summarize(found, delta(before, after))

    assert measured.requests == 1.0
    assert measured.ttft_ms == 500.0  # 0.5 s over one request
    assert measured.prompt_tokens == 4000.0
    assert measured.generation_tokens == 64.0
    assert measured.prefix_cache_queries == 4096.0
    assert measured.prefix_hit_rate == 0.75


def test_a_missing_histogram_reads_as_unknown_not_as_zero() -> None:
    before, after = parse_metrics(SAMPLE), parse_metrics(after_one_request())

    measured = summarize(discover(after), delta(before, after))

    assert measured.prefill_ms is None
    assert measured.tpot_ms is None


def test_a_counter_that_did_not_move_reads_as_zero_not_as_unknown() -> None:
    """A cache that was queried and missed every time is a measurement.

    `delta` keeps only what changed, so an unmoved counter is absent from it.
    Reporting that as unknown would hide the most informative case scenario C
    has: the request that paid full prefill.
    """

    unmoved = after_one_request().replace(
        "vllm:gpu_prefix_cache_hits{" + MODEL + "} 3072.0",
        "vllm:gpu_prefix_cache_hits{" + MODEL + "} 0.0",
    )
    before, after = parse_metrics(SAMPLE), parse_metrics(unmoved)

    measured = summarize(discover(after), delta(before, after))

    assert measured.prefix_cache_hits == 0.0
    assert measured.prefix_hit_rate == 0.0


def test_a_cache_nobody_queried_has_no_hit_rate() -> None:
    assert Measurement(prefix_cache_queries=0, prefix_cache_hits=0).prefix_hit_rate is None


def test_an_empty_reading_parses_to_nothing() -> None:
    assert parse_metrics("") == Snapshot()
