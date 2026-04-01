"""Set Active Floor widget UI for OpenAI host adapter."""

from __future__ import annotations

import json
from typing import Any


_SAMPLE_WIDGET_DATA: dict[str, Any] = {
    "floor_ref": "rmm",
    "floor_id": "rmm",
    "floor_title": "Royal Meenakshi Mall",
    "floor_description": "Royal Meenakshi Mall is South Bangalore's first complete mall destination with shopping, dining, and entertainment.",
    "floor_logo_url": "https://appfloor-public-assets.s3.ap-south-1.amazonaws.com/xfloor/rmm-logo.png",
    "blocks": [
        {"name": "Feeds"},
        {"name": "Poll"},
        {"name": "Posts"},
        {"name": "About"},
        {"name": "Offers"},
        {"name": "Locate Us"},
        {"name": "Events"},
    ],
}


def _build_widget_document(*, preview_data: dict[str, Any] | None = None) -> str:
    initial_data_json = json.dumps(preview_data or {})
    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>xFloor Active Floor Widget</title>
    <style>
      :root {{ color-scheme: light; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; padding: 12px; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: #f6f7fb; color: #111827; }}
      .widget-shell {{ width: 100%; max-width: 706px; margin: 0 auto; }}
      .card {{ background: #ffffff; border: 1px solid #e6e8ef; border-radius: 18px; box-shadow: 0 10px 28px rgba(16, 24, 40, 0.08); padding: 16px; }}
      .head {{ display: flex; align-items: flex-start; gap: 12px; min-width: 0; }}
      .logo {{ width: 54px; height: 54px; border-radius: 12px; border: 1px solid #e5e7eb; object-fit: cover; flex: 0 0 auto; }}
      .title-wrap {{ min-width: 0; }}
      .title {{ margin: 0; font-size: 18px; line-height: 1.3; font-weight: 700; color: #0f172a; word-break: break-word; }}
      .ref {{ margin: 4px 0 0 0; font-size: 12px; color: #64748b; overflow-wrap: anywhere; }}
      .description {{ margin: 14px 0 0 0; font-size: 14px; line-height: 1.5; color: #334155; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
      .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0 0; padding: 0; list-style: none; }}
      .chip {{ display: inline-flex; align-items: center; padding: 6px 10px; border-radius: 999px; border: 1px solid #e2e8f0; background: #f8fafc; color: #1f2937; font-size: 12px; line-height: 1; }}
      .chip.more {{ border-style: dashed; color: #475569; }}
      .cta-row {{ margin-top: 16px; }}
      .cta {{ display: inline-flex; align-items: center; justify-content: center; min-height: 38px; padding: 0 14px; border-radius: 10px; background: #0f172a; color: #ffffff; text-decoration: none; font-size: 13px; font-weight: 600; }}
      .cta:hover {{ background: #1e293b; }}
      .empty {{ color: #64748b; font-size: 13px; }}
    </style>
  </head>
  <body>
    <div class=\"widget-shell\" id=\"widget-root\"></div>
    <script>
      const PREVIEW_DATA = {initial_data_json};

      function normalizeText(value) {{
        return typeof value === "string" ? value.trim() : "";
      }}

      function floorUrlFrom(data) {{
        const floorId = normalizeText(data.floor_id);
        if (floorId) return `https://${{floorId}}.xfloor.ai`;
        const floorRef = normalizeText(data.floor_ref).replace(/^@/, "");
        return floorRef ? `https://${{floorRef}}.xfloor.ai` : "";
      }}

      function getStructuredContent() {{
        if (Object.keys(PREVIEW_DATA).length) return PREVIEW_DATA;
        const api = window.openai || {{}};
        return (
          window.structuredContent ||
          window.__structuredContent ||
          (api.toolOutput && api.toolOutput.structuredContent) ||
          {{}}
        );
      }}

      function renderSetActiveFloorWidget(data) {{
        const root = document.getElementById("widget-root");
        const floorRefRaw = normalizeText(data.floor_ref).replace(/^@/, "");
        const floorRef = floorRefRaw ? `@${{floorRefRaw}}` : "";
        const title = normalizeText(data.floor_title) || floorRef || "xFloor";
        const description = normalizeText(data.floor_description);
        const logo = normalizeText(data.floor_logo_url);
        const blocks = Array.isArray(data.blocks) ? data.blocks : [];
        const floorUrl = floorUrlFrom(data);

        const chips = [];
        for (const block of blocks.slice(0, 6)) {{
          const name = normalizeText(block && (block.name || block.block_id)) || "Unnamed";
          chips.push(`<li class=\"chip\">${{escapeHtml(name)}}</li>`);
        }}
        if (blocks.length > 6) {{
          chips.push(`<li class=\"chip more\">+${{blocks.length - 6}} more</li>`);
        }}

        root.innerHTML = `
          <section class=\"card\" aria-label=\"Active floor summary\">
            <div class=\"head\">
              ${{logo ? `<img class=\"logo\" src=\"${{escapeAttr(logo)}}\" alt=\"${{escapeAttr(title)}} logo\" />` : ""}}
              <div class=\"title-wrap\">
                <h1 class=\"title\">${{escapeHtml(title)}}</h1>
                ${{floorRef ? `<p class=\"ref\">${{escapeHtml(floorRef)}}</p>` : ""}}
              </div>
            </div>
            ${{description ? `<p class=\"description\">${{escapeHtml(description)}}</p>` : ""}}
            ${{chips.length ? `<ul class=\"chips\" aria-label=\"Floor blocks\">${{chips.join("")}}</ul>` : ""}}
            <div class=\"cta-row\">
              ${{floorUrl ? `<a class=\"cta\" href=\"${{escapeAttr(floorUrl)}}\" target=\"_blank\" rel=\"noopener noreferrer\">Open floor</a>` : `<span class=\"empty\">No floor URL available.</span>`}}
            </div>
          </section>
        `;
      }}

      function escapeHtml(input) {{
        return String(input)
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }}

      function escapeAttr(input) {{
        return escapeHtml(input);
      }}

      renderSetActiveFloorWidget(getStructuredContent());
    </script>
  </body>
</html>"""


def build_set_active_floor_widget_html() -> str:
    """Return OpenAI widget HTML payload for resource registration."""

    return _build_widget_document()


def build_set_active_floor_preview_html() -> str:
    """Return a standalone preview page for local screenshots."""

    return _build_widget_document(preview_data=_SAMPLE_WIDGET_DATA)
