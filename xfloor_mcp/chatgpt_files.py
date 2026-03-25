"""Helpers for strict ChatGPT widget attachment handling."""

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


async def download_chatgpt_attachment(
    attachment: dict[str, Any],
    *,
    timeout_s: float = 20.0,
) -> tuple[dict[str, str], str, str]:
    """Download one strict widget attachment and map it to xFloor multipart format."""

    download_url = str(attachment.get("download_url") or "").strip()
    file_id = str(attachment.get("file_id") or "").strip()
    if not file_id:
        raise AttachmentBridgeError("Attachment object is missing required field 'file_id'.")
    if not download_url:
        raise AttachmentBridgeError(
            "Attachment object is missing required field 'download_url'. Widget must call getFileDownloadUrl first."
        )

    logger.info("Attachment bridge: file download initiated file_id=%s", file_id)
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            response = await client.get(download_url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise AttachmentBridgeError(
                f"Could not fetch ChatGPT attachment bytes for file_id '{file_id}'."
            ) from exc

    filename = _filename_from_headers_or_url(response.headers, download_url, 1)
    mime_type = _mime_from_headers_or_filename(response.headers, filename)
    raw_bytes = response.content
    logger.info("Attachment bridge: file download completed file_id=%s filename=%s", file_id, filename)

    return (
        {
            "filename": filename,
            "content_base64": base64.b64encode(raw_bytes).decode("ascii"),
            "mime_type": mime_type,
        },
        file_id,
        filename,
    )
