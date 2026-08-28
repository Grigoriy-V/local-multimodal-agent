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
    assert "CONTROL_REGION" not in text
    assert "region=CONTROL_REGION" not in text


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
    assert "process_telegram_update.spawn(update_id)" in source()


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


def test_webhook_explicitly_stays_outside_modal_proxy_auth() -> None:
    assert "requires_proxy_auth=False" in source()
    assert "request: Request" in source()
