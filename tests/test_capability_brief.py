"""The assistant's account of itself, checked against what is wired up.

These tests exist because of two live failures, not a hypothesis. Asked for a
screenshot, the assistant said its "output supports only text" while the adapter
was sending screenshots; in the same run it reported a `browser.inspect` tool as
unavailable, a capability name it had turned into a tool that never existed.

So the properties under test are: the description is generated, it is complete,
it contains nothing invented, and the hand-written part of the prompt cannot
quietly outlive the tools it names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.agent.runtime import Agent
from app.attachments import ACCEPTED_MEDIA_TYPES
from app.capabilities import (
    CHAT_DELIVERY,
    TEXT_ONLY,
    Delivery,
    capability_brief,
    capability_report,
    tool_inventory,
)
from app.context.window import DEFAULT_SYSTEM_PROMPT
from app.memory import SqliteStore
from app.tools import (
    BROWSER_INSPECT,
    FILESYSTEM_READ,
    CapabilityRegistry,
    Toolbox,
    memory_tools,
)
from tests.fakes import ScriptedBackend, prompt_text, says, user


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    room = tmp_path / "workspace"
    room.mkdir()
    return room


@pytest.fixture
def registry(workspace: Path) -> CapabilityRegistry:
    return CapabilityRegistry(workspace)


def everything(registry: CapabilityRegistry) -> Toolbox:
    return registry.toolbox(registry.grant())


# --- the inventory is generated, not typed -----------------------------------


def test_the_brief_names_every_tool_the_agent_holds(registry: CapabilityRegistry) -> None:
    tools = everything(registry)

    brief = capability_brief(tools)

    assert tools.names
    for name in tools.names:
        assert name in brief


def test_a_narrower_grant_produces_a_narrower_brief(registry: CapabilityRegistry) -> None:
    """The tool the model invented a name for is absent when it is not granted."""

    reading_only = registry.toolbox(registry.grant(capabilities=(FILESYSTEM_READ,)))

    brief = capability_brief(reading_only)

    assert "read_file" in brief
    assert "inspect_page" not in brief
    assert "write_file" not in brief


def test_the_brief_grows_with_the_tools_it_is_given(registry: CapabilityRegistry) -> None:
    """A tool added outside the registry is described too, or the list lies."""

    store = SqliteStore(":memory:")
    try:
        with_memory = registry.toolbox(
            registry.grant(capabilities=(BROWSER_INSPECT,)),
            memory_tools(store, "someone", "thread", 5),
        )
    finally:
        store.close()

    brief = capability_brief(with_memory)

    assert "remember_fact" in brief
    assert "search_memory" in brief


def test_the_brief_lists_exactly_the_tools_that_ask_first(
    registry: CapabilityRegistry,
) -> None:
    tools = everything(registry)

    approval_line = next(
        line for line in capability_brief(tools).splitlines() if "approves" in line
    )

    assert "write_file" in approval_line
    assert "edit_file" in approval_line
    assert "read_file" not in approval_line
    assert "inspect_page" not in approval_line


def test_the_brief_covers_every_media_type_the_policy_admits(
    registry: CapabilityRegistry,
) -> None:
    """The admission policy is the only source for what can arrive."""

    brief = capability_brief(everything(registry))

    for media_type in ACCEPTED_MEDIA_TYPES:
        assert media_type in brief


# --- what leaves is the interface's fact, not the model's guess ---------------


def test_an_interface_that_shows_media_says_media_arrives(
    registry: CapabilityRegistry,
) -> None:
    brief = capability_brief(everything(registry), CHAT_DELIVERY)

    assert "image" in brief
    assert "explicitly call send_file" in brief
    assert "nothing else is sent automatically" in brief


def test_an_interface_that_cannot_show_media_says_that_instead(
    registry: CapabilityRegistry,
) -> None:
    """A future caller with no rendering must not be told pictures arrive."""

    brief = capability_brief(everything(registry), TEXT_ONLY)

    assert "no explicit file-delivery action" in brief
    assert "explicitly call send_file" not in brief


def test_a_text_only_agent_does_not_receive_a_send_tool(
    tmp_path: Path, workspace: Path
) -> None:
    agent = Agent(
        ScriptedBackend(),
        SqliteStore(tmp_path / "text-only.sqlite3"),
        workspace,
        delivery=TEXT_ONLY,
    )
    try:
        assert "send_file" not in agent.toolbox("thread").names
    finally:
        agent.store.close()


def test_a_declared_kind_reaches_the_model(registry: CapabilityRegistry) -> None:
    brief = capability_brief(everything(registry), Delivery(media=("image",)))

    assert "can deliver image" in brief
    assert "audio" in brief  # still accepted as input
    assert "nothing else is sent automatically" in brief


# --- the hand-written prompt cannot outlive its tools -------------------------


def test_the_default_prompt_names_only_tools_that_exist(
    registry: CapabilityRegistry,
) -> None:
    """Guidance may name tools; it may not name ones that are gone.

    The prompt says which tool suits which job, which is worth keeping in
    words. What is not worth keeping is a name that stops existing, so the only
    snake_case words the prompt is allowed to contain are real tool names.
    """

    store = SqliteStore(":memory:")
    try:
        tools = registry.toolbox(
            registry.grant(), memory_tools(store, "someone", "thread", 5)
        )
    finally:
        store.close()

    mentioned = set(re.findall(r"\b[a-z]+_[a-z_]+\b", DEFAULT_SYSTEM_PROMPT))

    assert mentioned <= set(tools.names)
    assert mentioned == set(tools.names), "a wired-up tool is undocumented in the prompt"


def test_the_inventory_closes_the_list_wherever_tools_are_given() -> None:
    """Every model call that receives tools receives this sentence."""

    sentence = tool_inventory(Toolbox())

    assert "none" in sentence
    assert "no others" in sentence


# --- the person can check the model's answer ---------------------------------


def test_the_report_states_what_the_agent_can_see_hear_send_and_change(
    registry: CapabilityRegistry, workspace: Path
) -> None:
    report = capability_report(everything(registry), CHAT_DELIVERY, workspace)

    assert "image/png" in report
    assert "audio/ogg" in report
    assert "write_file" in report
    assert str(workspace) in report


def test_the_agents_own_report_includes_its_memory_tools_and_root(
    tmp_path: Path, workspace: Path
) -> None:
    agent = Agent(ScriptedBackend(), SqliteStore(tmp_path / "m.sqlite3"), workspace)
    try:
        report = agent.capabilities("thread")
    finally:
        agent.store.close()

    assert "remember_fact" in report
    assert "inspect_page" in report
    assert str(workspace.resolve()) in report


# --- and the model is actually told ------------------------------------------


async def test_the_model_is_sent_the_derived_brief_every_turn(
    tmp_path: Path, workspace: Path
) -> None:
    backend = ScriptedBackend(says("hello"))
    agent = Agent(backend, SqliteStore(tmp_path / "m.sqlite3"), workspace)
    try:
        await agent.answer("thread", user("hi"))
    finally:
        await agent.aclose()

    sent = prompt_text(backend.requests[0])
    assert "Your tools are exactly" in sent
    assert "inspect_page" in sent
    assert "remember_fact" in sent


def test_the_person_is_told_which_documents_can_be_read(
    registry: CapabilityRegistry,
) -> None:
    """`/can` has to name this, because nothing else does.

    A document does not arrive as something the model can see, so an assistant
    that lists only images and audio reads as one that refuses PDFs — which is
    what it did until the tool existed.
    """

    from app.capabilities import capability_report

    tools = registry.toolbox(registry.grant())
    report = capability_report(tools)

    assert "Read: csv, docx, md, pdf, txt" in report
    assert "read_document" in report
    assert "view_pages" in report


def test_the_brief_never_says_a_document_cannot_be_seen(
    registry: CapabilityRegistry,
) -> None:
    """It said exactly that, and the assistant repeated it to a person.

    Asked to show the PDF it had just summarized, the assistant answered that it
    is a text model with no way to display anything — while holding a tool that
    renders the page and an interface that delivers pictures. The sentence that
    caused it was in the generated brief, which is the one place that is supposed
    to be incapable of being wrong about this.
    """

    from app.capabilities import capability_brief

    brief = capability_brief(registry.toolbox(registry.grant()))

    assert "never shown to you" not in brief
    assert "view_pages" in brief


def test_the_brief_separates_observation_from_explicit_presentation(
    registry: CapabilityRegistry,
) -> None:
    """Looking at a page is not a hidden request for the adapter to send it."""

    from app.capabilities import capability_brief

    brief = capability_brief(registry.toolbox(registry.grant()))

    assert "view_pages" in brief
    assert "sends nothing by itself" in brief
    assert "explicitly call send_file" in brief
