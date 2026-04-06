"""Query Current Floor widget HTML shell for OpenAI host adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SAMPLE_QUERY_DATA: dict[str, Any] = {
    "answer": (
        "Trends\n\n"
        "Up to 70% off + extra 10% off on fresh merchandise\n"
        "Covers men’s, women’s, and kids’ wear\n"
        "The listing is dated December 10–14, 2024, so it may be an older limited-time offer\n\n"
        "Monte Carlo\n\n"
        "Up to 50% off\n"
        "Best winter-clothing lead from the current floor content: Monte Carlo."
    ),
    "relatedFloors": [
        {"floor_id": "showoff", "label": "@showoff"},
        {"floor_id": "montecarlo", "label": "@montecarlo"},
        {"floor_id": "trends", "label": "@Trends"},
    ],
}


def _asset_base(asset_base_url: str | None) -> str:
    normalized = (asset_base_url or "").strip().rstrip("/")
    return normalized or ""


def _load_inline_assets() -> tuple[str | None, str | None]:
    candidates = [
        Path(__file__).resolve().parents[4] / "openai_widget" / "dist",
        Path.cwd() / "openai_widget" / "dist",
        Path("/app/openai_widget/dist"),
    ]
    dist_dir = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    style_path = dist_dir / "assets" / "style.css"
    script_path = dist_dir / "query-current-floor.js"

    style_text = style_path.read_text(encoding="utf-8") if style_path.exists() else None
    script_text = script_path.read_text(encoding="utf-8") if script_path.exists() else None
    return style_text, script_text


def _build_query_current_floor_document(*, asset_base_url: str | None = None, preview_data: dict[str, Any] | None = None) -> str:
    preview_json = json.dumps(preview_data or {}, ensure_ascii=False).replace("</", "<\\/")
    base = _asset_base(asset_base_url)
    script_src = f"{base}/openai-widget/query-current-floor.js" if base else "/openai-widget/query-current-floor.js"
    style_href = f"{base}/openai-widget/assets/style.css" if base else "/openai-widget/assets/style.css"
    inline_style, inline_script = _load_inline_assets()
    style_block = (
        f"<style>{inline_style}</style>"
        if inline_style
        else f"<link rel=\"stylesheet\" href=\"{style_href}\" />"
    )
    script_block = (
        f"<script>{inline_script}</script>"
        if inline_script
        else f"<script type=\"module\" src=\"{script_src}\"></script>"
    )
    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <meta name=\"xfloor-widget-source\" content=\"react-ts-vite:query-current-floor\" />
    <title>xFloor Query Result Widget</title>
    {style_block}
  </head>
  <body>
    <div id=\"root\"></div>
    <script id=\"widget-preview-data\" type=\"application/json\">{preview_json}</script>
    {script_block}
  </body>
</html>"""


def build_query_current_floor_widget_html(*, asset_base_url: str | None = None) -> str:
    return _build_query_current_floor_document(asset_base_url=asset_base_url)


def build_query_current_floor_preview_html(*, asset_base_url: str | None = None) -> str:
    return _build_query_current_floor_document(asset_base_url=asset_base_url, preview_data=_SAMPLE_QUERY_DATA)
