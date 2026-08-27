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


@dataclass(frozen=True)
class AttachmentBytes:
    """An upload an interface already holds in memory rather than on disk."""

    name: str
    media_type: str | None
    data: bytes


def _check_size(name: str, size: int) -> int:
    if size == 0:
        raise AttachmentError(f"{name}: empty files are not supported")
    if size > MAX_FILE_SIZE_BYTES:
        raise AttachmentError(f"{name}: file exceeds the 20 MB limit")
    return size


def _check_kind(name: str, media_type: str | None) -> str:
    if media_type not in MEDIA_KINDS:
        raise AttachmentError(f"{name}: unsupported file type ({media_type or 'unknown type'})")
    return MEDIA_KINDS[media_type]


def _check_count(count: int) -> None:
    if count > MAX_FILES:
        raise AttachmentError(f"at most {MAX_FILES} files can be sent in one message")


def _check_total(sizes: Sequence[int]) -> None:
    if sum(sizes) > MAX_TOTAL_SIZE_BYTES:
        raise AttachmentError("attachments exceed the 50 MB total limit")


def _size(source: AttachmentSource) -> int:
    try:
        if not source.path.is_file():
            raise AttachmentError(f"{source.name}: uploaded file is unavailable")
        size = source.path.stat().st_size
    except OSError as exc:
        raise AttachmentError(f"{source.name}: uploaded file is unavailable") from exc
    return _check_size(source.name, size)


def load_attachment_bytes(uploads: Sequence[AttachmentBytes]) -> tuple[ContentPart, ...]:
    """Admit uploads an interface received as bytes, under the same limits.

    Telegram hands over file contents rather than paths. Writing them to disk
    only to read them back would put a second, quietly different admission
    policy in the adapter, so both paths meet here instead.
    """

    _check_count(len(uploads))
    kinds = [_check_kind(upload.name, upload.media_type) for upload in uploads]
    sizes = [_check_size(upload.name, len(upload.data)) for upload in uploads]
    _check_total(sizes)
    return tuple(
        ContentPart(kind=kind, data=upload.data, media_type=upload.media_type)
        for kind, upload in zip(kinds, uploads, strict=True)
    )


def load_attachments(sources: Sequence[AttachmentSource]) -> tuple[ContentPart, ...]:
    """Validate a complete upload batch, then read it into domain messages.

    The batch is all-or-nothing: one bad file refuses the whole user message so
    the model cannot answer as though it had seen an attachment that was lost.
    """

    _check_count(len(sources))
    sizes: list[int] = []
    for source in sources:
        _check_kind(source.name, source.media_type)
        sizes.append(_size(source))
    _check_total(sizes)

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
