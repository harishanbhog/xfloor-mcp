"""Helpers for ChatGPT MCP file parameters.

Converts ChatGPT top-level file params ({download_url, file_id}) into the
internal xFloor multipart file format expected by XFloorClient.create_event.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


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


async def download_chatgpt_attachments(
    attachment: dict[str, Any] | None,
    attachments: list[dict[str, Any]] | None,
    *,
    timeout_s: float = 20.0,
) -> tuple[list[dict[str, str]] | None, list[str], list[str]]:
    """Download ChatGPT file params and convert to xFloor file objects.

    Returns: (files_payload, file_ids, filenames)
    """

    items: list[dict[str, Any]] = []
    if attachment:
        items.append(attachment)
    if attachments:
        items.extend(attachments)

    if not items:
        return None, [], []

    converted: list[dict[str, str]] = []
    file_ids: list[str] = []
    filenames: list[str] = []

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for idx, item in enumerate(items, start=1):
            download_url = str(item.get("download_url") or "").strip()
            file_id = str(item.get("file_id") or "").strip()
            if not download_url:
                raise ValueError("Attachment is missing download_url.")
            if not file_id:
                raise ValueError("Attachment is missing file_id.")

            logger.info("Downloading ChatGPT attachment file_id=%s", file_id)
            try:
                response = await client.get(download_url)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"Could not fetch ChatGPT attachment for file_id '{file_id}'.") from exc

            filename = _filename_from_headers_or_url(response.headers, download_url, idx)
            mime_type = _mime_from_headers_or_filename(response.headers, filename)
            content_base64 = base64.b64encode(response.content).decode("ascii")

            converted.append(
                {
                    "filename": filename,
                    "content_base64": content_base64,
                    "mime_type": mime_type,
                }
            )
            file_ids.append(file_id)
            filenames.append(filename)

    return converted, file_ids, filenames
