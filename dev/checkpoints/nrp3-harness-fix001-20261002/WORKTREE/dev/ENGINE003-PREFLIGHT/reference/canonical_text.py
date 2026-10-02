#!/usr/bin/env python3
"""Canonical LF-only text bytes for portable ENGINE003 review artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def lf_text_bytes(text: str, encoding: str = "utf-8") -> bytes:
    """Encode text after rejecting any embedded carriage-return byte."""
    raw = text.encode(encoding)
    if b"\r" in raw:
        raise ValueError("canonical portable text contains a CR byte")
    return raw


def canonical_json_bytes(value: Any, *, sort_keys: bool = False) -> bytes:
    """Render indented JSON as UTF-8 plus exactly one trailing LF byte."""
    return lf_text_bytes(
        json.dumps(value, indent=2, sort_keys=sort_keys, ensure_ascii=True) + "\n"
    )


def write_canonical_json(
    path: Path, value: Any, *, sort_keys: bool = False
) -> None:
    path.write_bytes(canonical_json_bytes(value, sort_keys=sort_keys))

