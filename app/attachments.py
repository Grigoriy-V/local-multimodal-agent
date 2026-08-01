"""UI-independent admission policy for user-supplied attachments.

An interface may reject a file earlier for a nicer experience, but this module
is the authoritative boundary.  A future UI or API gets the same limits by
calling :func:`load_attachments` before starting an agent turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.models import ContentPart

MAX_FILES = 5
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_SIZE_BYTES = 50 * 1024 * 1024

MEDIA_KINDS = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/mpeg": "audio",
    "audio/flac": "audio",
    "audio/ogg": "audio",
}
ACCEPTED_MEDIA_TYPES = tuple(MEDIA_KINDS)


class AttachmentError(ValueError):
    """An incoming attachment cannot safely become model input."""


@dataclass(frozen=True)
class AttachmentSource:
    path: Path
    media_type: str | None
    name: str


def _size(source: AttachmentSource) -> int:
    try:
        if not source.path.is_file():
            raise AttachmentError(f"{source.name}: uploaded file is unavailable")
        size = source.path.stat().st_size
    except OSError as exc:
        raise AttachmentError(f"{source.name}: uploaded file is unavailable") from exc
    if size == 0:
        raise AttachmentError(f"{source.name}: empty files are not supported")
    if size > MAX_FILE_SIZE_BYTES:
        raise AttachmentError(f"{source.name}: file exceeds the 20 MB limit")
    return size


def load_attachments(sources: Sequence[AttachmentSource]) -> tuple[ContentPart, ...]:
    """Validate a complete upload batch, then read it into domain messages.

    The batch is all-or-nothing: one bad file refuses the whole user message so
    the model cannot answer as though it had seen an attachment that was lost.
    """

    if len(sources) > MAX_FILES:
        raise AttachmentError(f"at most {MAX_FILES} files can be sent in one message")

    sizes: list[int] = []
    for source in sources:
        if source.media_type not in MEDIA_KINDS:
            media_type = source.media_type or "unknown type"
            raise AttachmentError(f"{source.name}: unsupported file type ({media_type})")
        sizes.append(_size(source))

    if sum(sizes) > MAX_TOTAL_SIZE_BYTES:
        raise AttachmentError("attachments exceed the 50 MB total limit")

    parts = []
    for source in sources:
        try:
            data = source.path.read_bytes()
        except OSError as exc:
            raise AttachmentError(f"{source.name}: uploaded file is unavailable") from exc
        parts.append(
            ContentPart(
                kind=MEDIA_KINDS[source.media_type],
                data=data,
                media_type=source.media_type,
            )
        )
    return tuple(parts)
