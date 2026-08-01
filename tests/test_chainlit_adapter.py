"""The only part of the UI worth testing offline: the adaptation to `Message`.

Rendering is Chainlit's; turning an attachment into a content part is ours, and
a wrong media type there fails silently against a live model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("chainlit", reason="the ui dependency group is optional")

from app.memory import Thread
from app.models import ContentPart, Message
from ui.chainlit_app import media_parts, part_for, rejected, spoken, summarise, to_message


class FakeElement:
    def __init__(self, path: str, mime: str | None, name: str | None = None) -> None:
        self.path = path
        self.mime = mime
        self.name = name


class FakeMessage:
    def __init__(self, content: str = "", elements: list[FakeElement] | None = None) -> None:
        self.content = content
        self.elements = elements or []


def test_a_plain_message_becomes_one_text_part() -> None:
    message = to_message(FakeMessage("hello"))

    assert message.role == "user"
    assert [part.kind for part in message.content] == ["text"]


def test_an_image_attachment_keeps_its_bytes_and_media_type(tmp_path: Path) -> None:
    picture = tmp_path / "shot.png"
    picture.write_bytes(b"\x89PNG\x00")

    message = to_message(FakeMessage("what is this", [FakeElement(str(picture), "image/png")]))

    assert [part.kind for part in message.content] == ["text", "image"]
    assert message.content[1].data == b"\x89PNG\x00"
    assert message.content[1].media_type == "image/png"


def test_an_audio_attachment_is_carried_as_audio(tmp_path: Path) -> None:
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFF")

    message = to_message(FakeMessage("", [FakeElement(str(clip), "audio/wav")]))

    assert [part.kind for part in message.content] == ["audio"]


def test_an_unsupported_attachment_is_ignored(tmp_path: Path) -> None:
    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF")

    assert part_for(str(document), "application/pdf") is None


def test_a_message_with_nothing_usable_still_produces_a_turn(tmp_path: Path) -> None:
    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF")

    message = to_message(FakeMessage("", [FakeElement(str(document), "application/pdf")]))

    assert message.content[0].text == "(empty message)"


def test_an_ignored_attachment_is_named_so_it_can_be_reported(tmp_path: Path) -> None:
    """Dropping a file in silence looks like the agent read it and said nothing."""

    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF")
    picture = tmp_path / "shot.png"
    picture.write_bytes(b"\x89PNG")

    incoming = FakeMessage(
        "look",
        [FakeElement(str(document), "application/pdf"), FakeElement(str(picture), "image/png")],
    )

    assert rejected(incoming) == ["report.pdf"]


def test_nothing_is_reported_when_everything_was_read(tmp_path: Path) -> None:
    picture = tmp_path / "shot.png"
    picture.write_bytes(b"\x89PNG")

    assert rejected(FakeMessage("look", [FakeElement(str(picture), "image/png")])) == []


# --- what comes back out -----------------------------------------------------


def test_media_is_picked_out_to_be_shown_not_described() -> None:
    """Building the Chainlit element is Chainlit's; choosing what to show is ours."""

    message = Message(
        role="user",
        content=[
            ContentPart(kind="text", text="what is this"),
            ContentPart(kind="image", data=b"\x89PNG", media_type="image/png"),
            ContentPart(kind="audio", data=b"RIFF", media_type="audio/wav"),
        ],
    )

    assert [part.media_type for part in media_parts(message)] == ["image/png", "audio/wav"]


def test_a_text_only_message_has_nothing_to_show() -> None:
    message = Message(role="assistant", content=[ContentPart(kind="text", text="hi")])

    assert media_parts(message) == []


def test_a_thread_is_labelled_by_how_it_began() -> None:
    thread = Thread(id="abc", updated_at="2026-08-01T00:00:00+00:00", messages=4, opening="hello")

    assert summarise(thread) == "hello · 4 messages"


def test_a_long_opening_is_cut_to_fit_a_button() -> None:
    thread = Thread(id="abc", updated_at="x", messages=2, opening="word " * 40)

    label = summarise(thread)

    assert label.startswith("word")
    assert "…" in label


def test_a_thread_that_began_without_words_is_still_recognisable() -> None:
    thread = Thread(id="abc", updated_at="x", messages=2, opening="")

    assert summarise(thread) == "(no words) · 2 messages"


def test_spoken_joins_only_the_text_parts() -> None:
    message = Message(
        role="assistant",
        content=[
            ContentPart(kind="text", text="here it is"),
            ContentPart(kind="image", data=b"\x89PNG", media_type="image/png"),
        ],
    )

    assert spoken(message) == "here it is"
