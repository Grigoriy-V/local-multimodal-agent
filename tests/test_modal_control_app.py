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
    assert '.uv_sync(\n    "."' in text
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


def _image_of(name: str) -> str:
    """The image a Modal function is declared with, read from the decorator."""

    tree = ast.parse(source())
    node = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "image" and isinstance(keyword.value, ast.Name):
                return keyword.value.id
    raise AssertionError(f"{name} declares no image")


def test_the_browser_is_installed_where_the_agent_runs() -> None:
    """`/check` reported FAIL browser.inspect because the image had no browser.

    The tool has always worked on the human's machine and never in a container,
    which is the exact shape of failure `preflight` exists to catch.
    """

    assert 'apt_install(\n    "chromium"' in source()
    assert _image_of("process_telegram_update") == "agent_image"
    assert _image_of("self_test") == "agent_image"


def test_the_webhook_does_not_carry_the_browser() -> None:
    """The one function a person waits on stays on the smaller layer.

    Chromium and its fonts are a few hundred megabytes and the webhook never
    renders anything; carrying them would spend the cold start that the import
    work was done to win back.
    """

    assert _image_of("telegram_webhook") == "control_image"


def test_screenshots_can_render_cyrillic() -> None:
    """A screenshot of text in boxes is a picture of nothing.

    debian_slim ships no fonts at all, and this assistant is used in Russian, so
    the font package is part of the capability rather than a nicety.
    """

    assert "fonts-dejavu-core" in source()


def _volumes_of(name: str) -> str | None:
    tree = ast.parse(source())
    node = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "volumes":
                return ast.unparse(keyword.value)
    return None


def test_the_workspace_outlives_the_container() -> None:
    """A file written in one message did not exist in the next one.

    The container's filesystem goes when it scales down, so the file tools were
    advertised and only ever half true. A volume, not a sandbox: whether a file
    survives and where untrusted content may run are separate questions.
    """

    assert 'modal.Volume.from_name("assistant-workspaces"' in source()
    assert _volumes_of("process_telegram_update") == "{WORKSPACE_ROOT: workspaces}"
    assert _volumes_of("self_test") == "{WORKSPACE_ROOT: workspaces}"
    assert '"AGENT_WORKSPACE": WORKSPACE_ROOT' in source()


def test_the_webhook_has_no_workspace_because_it_runs_no_tools() -> None:
    assert _volumes_of("telegram_webhook") is None


def test_a_turn_reloads_before_and_commits_after() -> None:
    """A warm container keeps serving the volume it first saw.

    Without the reload, a message answered by a container older than another
    container's write is answered against a stale workspace; without the commit,
    this turn's files are not there for the next one.
    """

    assert "await workspaces.reload.aio()" in source()
    assert "await workspaces.commit.aio()" in source()


def test_one_volume_is_not_one_workspace() -> None:
    """Each person keeps their own directory inside the shared volume.

    `user_workspace` is what puts them there, and `AGENTS.md` is explicit that a
    boundary shared by several people is not one.
    """

    from app.agent.runtime import user_workspace

    first = user_workspace("/workspaces", "telegram-1")
    second = user_workspace("/workspaces", "telegram-2")

    assert first != second
    assert first.parent == second.parent


def _keywords_of(name: str) -> dict[str, str]:
    """Every keyword argument on every decorator of one Modal function."""

    tree = ast.parse(source())
    node = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    return {
        keyword.arg: ast.unparse(keyword.value)
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        for keyword in decorator.keywords
        if keyword.arg is not None
    }


def test_the_page_renderer_holds_nothing_worth_reaching() -> None:
    """The isolation is what this function *is*, so it is asserted, not trusted.

    A page's own JavaScript runs here and nowhere else in the deployment, and
    Chromium under `--no-sandbox` as root has no isolation of its own. Rendering
    inside the update worker would put that code in the same container as
    TELEGRAM_TOKEN, MODEL_API_KEY and AGENT_DATABASE_URL. So this container gets
    no secret, no database, no workspace volume — and the assertion is here
    because the cheapest way to lose all of that is someone adding
    `secrets=[control_secret]` to make one thing easier.
    """

    renderer = _keywords_of("render_web_page")
    worker = _keywords_of("process_telegram_update")

    assert _image_of("render_web_page") == "render_image"
    assert "secrets" not in renderer
    assert "volumes" not in renderer
    # The contrast is the point: the worker does hold them.
    assert worker["secrets"] == "[control_secret]"
    assert worker["volumes"] == "{WORKSPACE_ROOT: workspaces}"


def test_the_page_renderer_is_not_a_url_fetcher_for_whoever_finds_it() -> None:
    """Unauthenticated, it would open any address for anyone on the internet."""

    assert _keywords_of("render_web_page")["requires_proxy_auth"] == "True"
    assert _keywords_of("telegram_webhook")["requires_proxy_auth"] == "False"


def test_the_renderer_shares_the_browser_layer_it_needs() -> None:
    assert "render_image = _with_source(_with_browser)" in source()


def test_the_worker_declares_that_it_does_not_open_web_pages_itself() -> None:
    """The worker's Chromium is for local artifacts with the network blocked.

    Without this the boundary would depend on one secret value being present:
    forget `WEB_RENDERER_URL` and the worker would fall back to its own browser,
    beside the bot token and the database URL, with nothing looking wrong.
    """

    assert '"WEB_LOCAL_BROWSER": "0"' in source()
    assert '"WEB_LOCAL_BROWSER"' not in _keywords_of("render_web_page").get("image", "")


def test_the_browser_is_installed_before_the_source_is_copied() -> None:
    """A copied directory invalidates every layer after it.

    The source changes on every deploy and Chromium pulls the whole X11 stack,
    so installing it above the copy reinstalled all of it every time - minutes
    of build for a one-line edit. Both images are assembled by one function that
    copies the source last, so this is a property of the order, not a habit.
    """

    text = source()

    assert text.index(".apt_install(") < text.index("def _with_source(")
    assert text.count('.add_local_dir("app"') == 1
    assert "control_image = _with_source(_dependencies)" in text
    assert "agent_image = _with_source(_with_browser)" in text
