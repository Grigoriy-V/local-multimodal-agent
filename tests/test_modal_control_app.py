"""Static guarantees for the Modal control adapter; importing starts nothing."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "deploy" / "modal" / "control_app.py"


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_control_app_is_cpu_only_and_separate_from_the_model_app() -> None:
    text = source()
    assert 'APP_NAME = "assistant-control"' in text
    assert "gpu=" not in text
    assert "assistant-llm-v2" not in text


def test_placement_stays_unpinned_because_pinning_costs_more_than_it_saves() -> None:
    """Not an oversight. Measured, costed and decided.

    Pinning a region multiplies the worker's whole lifetime by 1.75x, and the
    worker is alive for the entire message because it waits on the model:
    about $0.00033 a message. The latency it would remove is one to three
    database calls sitting between two model calls while the GPU is warm —
    about $0.00006. Four to eight times the cost for the smaller number.

    See `DECISIONS.md`, 2026-08-28. Reversing this needs a reason that is not
    money, since the whole question is worth about a dollar a month.
    """

    text = source()
    assert "region=" not in text
    assert "routing_region" not in text


def test_image_copies_only_application_source_not_secrets_or_workspaces() -> None:
    text = source()
    assert '.uv_sync(\n        "."' in text
    assert '.add_local_dir("app"' in text
    assert '.add_local_dir("ui"' in text
    assert (
        '"deploy/modal/control_app.py", "/root/project/control_app.py", copy=True'
        in text
    )
    assert '.add_local_dir("."' not in text
    assert 'add_local_file(".env"' not in text
    assert 'extra_options="--no-install-project"' in text


def test_webhook_and_worker_are_distinct_modal_functions() -> None:
    tree = ast.parse(source())
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "telegram_webhook" in functions
    assert "process_telegram_update" in functions
    # The async form, because the blocking one is a synchronous RPC from inside
    # the event loop the webhook is answering on.
    assert "await process_telegram_update.spawn.aio(update_id)" in source()


def test_database_latency_probe_is_cpu_only_and_does_not_call_the_model() -> None:
    tree = ast.parse(source())
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "measure_database_latency" in functions
    probe = ast.get_source_segment(source(), functions["measure_database_latency"])
    assert probe is not None
    assert "open_store" in probe
    assert "load_turn_context" in probe
    assert ".append(" in probe
    assert "ModelBackend" not in probe
    assert "MODEL_ENDPOINT" not in probe


def test_the_comparison_never_takes_a_dsn_as_an_argument() -> None:
    """A credential passed as an argument is a credential in the call record.

    The probe chooses between configured databases by name; the values stay in
    the platform secret where they already are.
    """

    tree = ast.parse(source())
    probe = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "measure_database_latency"
    )
    parameters = [argument.arg for argument in probe.args.args]

    assert parameters == ["operation", "warm_runs", "database"]
    assert 'database not in {"primary", "alternate"}' in source()


def test_the_two_databases_are_measured_in_one_invocation() -> None:
    """Placement is unpinned, so two calls can land in two regions.

    Measured separately, the difference between the results would include the
    difference between the workers — which is the thing being controlled for.
    """

    text = source()
    assert '"primary": sample(profile("primary"), read_once)' in text
    assert '"alternate": sample(profile("alternate"), read_once)' in text


def test_webhook_explicitly_stays_outside_modal_proxy_auth() -> None:
    assert "requires_proxy_auth=False" in source()
    assert "request: Request" in source()


def test_the_webhook_does_not_ask_for_a_memory_snapshot() -> None:
    """Measured, not assumed, and the measurement said no.

    Nine deployed cold starts: 5.36 s mean without snapshots, 8.56 s while
    creating one, 4.06 s restoring one. Subtracting execution shows the
    container itself costs ~3.5 s either way — a restore skips initialization,
    not scheduling, and this function's initialization had already been removed
    by keeping the agent stack out of its imports. Six of the nine were still
    creating, because a snapshot only restores onto the worker type that made
    it and placement here is unpinned.

    Turning it back on needs a new measurement, not a new hope.
    """

    tree = ast.parse(source())
    passed = {
        keyword.arg
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        for keyword in decorator.keywords
    }

    # The name appears in the comment that explains the decision, so this asks
    # the syntax whether it is an argument rather than asking the text.
    assert "enable_memory_snapshot" not in passed
