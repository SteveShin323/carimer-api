"""Turning whatever the caller has into the base64 `photoBinary` the API wants."""

from __future__ import annotations

import base64
import os
from pathlib import Path

__all__ = ["encode_image"]


def encode_image(source: bytes | bytearray | str | os.PathLike[str]) -> str:
    """Base64 of the image bytes.

    `bytes` are the image itself. A `str` or `PathLike` is a **filesystem path** — never
    pre-encoded base64 and never a URL, so that a caller who passes the wrong thing gets
    a `FileNotFoundError` instead of a search for nothing.
    """
    data = bytes(source) if isinstance(source, bytes | bytearray) else Path(os.fspath(source)).read_bytes()
    if not data:
        raise ValueError("image is empty")
    return base64.b64encode(data).decode("ascii")
