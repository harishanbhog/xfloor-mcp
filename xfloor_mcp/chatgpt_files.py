"""Helpers for ChatGPT MCP file parameters.

Converts ChatGPT top-level file params into the internal xFloor multipart file
format expected by ``XFloorClient.create_event``.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AttachmentBridgeError(ValueError):
    """Raised when ChatGPT attachment handoff cannot be bridged."""

    message: str

    def __str__(self) -> str:
        return self.message


def _filename_from_headers_or_url(headers: httpx.Headers, download_url: str, index: int) -> str:
    content_disposition = headers.get("content-disposition", "")
    marker = "filename="
    if marker in content_disposition.lower():
        raw = content_disposition.split("filename=", 1)[1].strip().strip('"').strip("'")
        if raw:
            return raw

    parsed = urlparse(download_url)
    basename = os.path.basename(parsed.path or "")
    if basename:
        return basename
    return f"attachment-{index}"


def _mime_from_headers_or_filename(headers: httpx.Headers, filename: str) -> str:
    content_type = (headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return (guessed or "application/octet-stream").lower()


def _coerce_attachment_items(
    attachment: dict[str, Any] | str | None,
    attachments: list[dict[str, Any] | str] | None,
) -> list[dict[str, Any] | str]:
    items: list[dict[str, Any] | str] = []
    if attachment is not None:
        items.append(attachment)
    if attachments:
        items.extend(attachments)
    return items


def _extract_local_path(item: dict[str, Any] | str) -> str:
    if isinstance(item, str):
        return item.strip()
    # Defensive dev-mode fallback keys.
    for key in ("file_path", "path", "local_path"):
        candidate = str(item.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


async def download_chatgpt_attachments(
    attachment: dict[str, Any] | str | None,
    attachments: list[dict[str, Any] | str] | None,
    *,
    timeout_s: float = 20.0,
) -> tuple[list[dict[str, str]] | None, list[str], list[str]]:
    """Download/read ChatGPT attachment params and convert to xFloor file objects.

    Supported per-item forms:
    - Official MCP file param object: ``{"download_url": ..., "file_id": ...}``
    - Dev fallback local path string: ``"/mnt/data/example.jpg"``

    Returns: (files_payload, file_ids, filenames)
    """

    items = _coerce_attachment_items(attachment, attachments)
    if not items:
        return None, [], []

    converted: list[dict[str, str]] = []
    file_ids: list[str] = []
    filenames: list[str] = []

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for idx, item in enumerate(items, start=1):
            download_url = ""
            file_id = ""
            if isinstance(item, dict):
                download_url = str(item.get("download_url") or "").strip()
                file_id = str(item.get("file_id") or "").strip()

            if download_url:
                logger.info("Attachment bridge source=download_url file_id=%s", file_id or "unknown")
                try:
                    response = await client.get(download_url)
                    response.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    raise AttachmentBridgeError(
                        f"Could not fetch ChatGPT attachment for file_id '{file_id or 'unknown'}'."
                    ) from exc

                filename = _filename_from_headers_or_url(response.headers, download_url, idx)
                mime_type = _mime_from_headers_or_filename(response.headers, filename)
                raw_bytes = response.content
            else:
                local_path = _extract_local_path(item)
                if not local_path:
                    raise AttachmentBridgeError(
                        "Attachment bridge could not use provided file reference. Expected download_url or readable local path."
                    )
                if not os.path.exists(local_path) or not os.path.isfile(local_path):
                    raise AttachmentBridgeError(
                        "Attachment bridge could not use provided file reference. Local path is not readable in this MCP environment."
                    )

                logger.info("Attachment bridge source=local_path filename=%s", os.path.basename(local_path))
                try:
                    with open(local_path, "rb") as f:
                        raw_bytes = f.read()
                except Exception as exc:  # noqa: BLE001
                    raise AttachmentBridgeError(
                        "Attachment bridge could not read provided local path in this MCP environment."
                    ) from exc
                filename = os.path.basename(local_path) or f"attachment-{idx}"
                mime_type = (mimetypes.guess_type(filename)[0] or "application/octet-stream").lower()

            converted.append(
                {
                    "filename": filename,
                    "content_base64": base64.b64encode(raw_bytes).decode("ascii"),
                    "mime_type": mime_type,
                }
            )
            file_ids.append(file_id)
            filenames.append(filename)

    return converted, file_ids, filenames
