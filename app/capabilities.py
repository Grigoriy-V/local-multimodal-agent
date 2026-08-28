"""What the assistant can actually do, stated from what is wired up.

Not `app/tools/capabilities.py`, which decides what a grant *permits*. This
module only reads results: the tools a toolbox really holds, the media the
admission policy really accepts, and the media the interface in front of the
agent really puts in the chat.

It exists because a hand-written sentence about abilities rots. Asked for a
screenshot, the assistant answered that its "output supports only text" while
the adapter was sending screenshots, and in the same run named a `browser.inspect`
tool that has never existed — a capability name from the plan, not a tool. Both
mistakes come from prose someone typed instead of a fact something read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.attachments import MAX_FILE_SIZE_BYTES, MAX_FILES, MEDIA_KINDS
from app.documents import DOCUMENT_MEDIA_TYPES
from app.tools import Toolbox


@dataclass(frozen=True)
class Delivery:
    """The media kinds this interface can put in front of the person.

    An adapter declares it because only the adapter knows. The same answer with
    the same picture in it reaches a Telegram user as a photo, a Chainlit user
    as an inline element, and a caller with no rendering at all as nothing —
    and the model has no way to find that out for itself.
    """

    media: tuple[str, ...] = ("image", "audio")


# Both interfaces that exist show pictures and play sound, so this is the honest
# default rather than a cautious one. An interface that cannot must say so.
CHAT_DELIVERY = Delivery()
TEXT_ONLY = Delivery(media=())


def accepted(kind: str) -> tuple[str, ...]:
    """The media types the admission policy accepts for one kind of input."""

    return tuple(media for media, admitted in MEDIA_KINDS.items() if admitted == kind)


def documents() -> str:
    """The document formats that can be read, named the way a person names them."""

    return ", ".join(sorted(DOCUMENT_MEDIA_TYPES.values()))


def needs_approval(tools: Toolbox) -> tuple[str, ...]:
    """The tools that do not run until the person says yes."""

    return tuple(name for name in tools.names if tools.destructive(name))


def tool_inventory(tools: Toolbox) -> str:
    """The one sentence that closes the list, wherever a model is given tools.

    Every model call in this project that receives tools also receives this, so
    an invented tool name is always contradicted in the same prompt.
    """

    names = ", ".join(tools.names) or "none"
    return (
        f"Your tools are exactly: {names}. There are no others. Never name a tool "
        "outside that list; if something is beyond them, say plainly what you cannot "
        "do rather than inventing a tool for it."
    )


def _delivery_sentence(delivery: Delivery) -> str:
    if not delivery.media:
        return (
            "Only the text of your answer reaches the person. Media you produce is "
            "not delivered here, so describe it instead of presenting it."
        )
    kinds = " or ".join(delivery.media)
    return (
        f"Your answer reaches the person as chat messages: the text is shown, and any "
        f"{kinds} a tool returns to you is sent to them as well, automatically. You do "
        "not attach it and there is no separate step: calling the tool is what sends it. "
        "So never say you cannot make, take or send a picture — call the tool that "
        "produces one and it arrives."
    )


def capability_brief(tools: Toolbox, delivery: Delivery = CHAT_DELIVERY) -> str:
    """The part of the system prompt that must never be written from memory.

    Deliberately short: the tool schemas already carry each tool's parameters
    and description, so this adds only what they cannot — that the list is
    exhaustive, what can arrive, and what can leave.
    """

    inputs = ", ".join(accepted("image") + accepted("audio")) or "text only"
    lines = [
        "Your real capabilities right now, generated from what is wired up:",
        f"- {tool_inventory(tools)}",
        f"- The person can send you text and these media types: {inputs}. Anything "
        "else is refused before you see it.",
        f"- {_delivery_sentence(delivery)}",
    ]
    if "read_document" in tools.names:
        # Said separately from the media list because it arrives differently: a
        # document is a file in the workspace rather than something already in
        # front of you. What this must not say is that you cannot see it — an
        # earlier version did, and the assistant duly told a person it was a text
        # model that could not look at the PDF it had just read.
        looking = (
            " view_pages turns a PDF page into an image: you see it, and the person is "
            "sent the same picture. That is how you show someone a page or a scan, and "
            "it is also how you read one that has no text layer."
            if "view_pages" in tools.names
            else ""
        )
        lines.append(
            f"- The person can also send documents ({documents()}). They are saved in "
            "your workspace under the name the turn gives you, and you read them with "
            f"read_document rather than receiving their text directly.{looking}"
        )
    asking = needs_approval(tools)
    if asking:
        lines.append(
            f"- These run only after the person approves them: {', '.join(asking)}. "
            "A declined call is final; say so and do not repeat it."
        )
    return "\n".join(lines)


def capability_report(
    tools: Toolbox,
    delivery: Delivery = CHAT_DELIVERY,
    root: Path | None = None,
) -> str:
    """The same facts for a person, so the model's answer can be checked.

    The point is that this is not the model talking. When the assistant claims
    it cannot see a picture or can run a tool it does not have, this is what the
    claim is measured against.
    """

    images = ", ".join(accepted("image")) or "nothing"
    audio = ", ".join(accepted("audio")) or "nothing"
    sends = ", ".join(("text",) + delivery.media)
    asking = ", ".join(needs_approval(tools)) or "nothing"
    megabytes = MAX_FILE_SIZE_BYTES // (1024 * 1024)
    lines = [
        "What I can do here, read from what is wired up rather than written by hand.",
        "",
        f"See: {images}",
        f"Hear: {audio}",
        f"Read: {documents() if 'read_document' in tools.names else 'no documents'}",
        f"Receive: up to {MAX_FILES} files per message, {megabytes} MB each",
        f"Send: {sends}",
        f"Tools: {', '.join(tools.names) or 'none'}",
        f"Ask first: {asking}",
    ]
    if root is not None:
        lines.append(f"Files: only inside {root}")
    return "\n".join(lines)
