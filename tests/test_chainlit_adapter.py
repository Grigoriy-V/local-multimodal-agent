"""The only part of the UI worth testing offline: the adaptation to `Message`.

Rendering is Chainlit's; turning an attachment into a content part is ours, and
a wrong media type there fails silently against a live model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("chainlit", reason="the ui dependency group is optional")

from app.models import ContentPart, Message
from ui.chainlit_app import part_for, spoken, to_message


class FakeElement:
    def __init__(self, path: str, mime: str | None) -> None:
        self.path = path
        self.mime = mime


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


def test_spoken_joins_only_the_text_parts() -> None:
    message = Message(
        role="assistant",
        content=[
            ContentPart(kind="text", text="here it is"),
            ContentPart(kind="image", data=b"\x89PNG", media_type="image/png"),
        ],
    )

    assert spoken(message) == "here it is"
