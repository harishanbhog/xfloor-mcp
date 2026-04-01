"""Query current floor widget UI for OpenAI host adapter."""

from __future__ import annotations

import json


_SAMPLE_QUERY_DATA = {
    "answer": (
        "Trends\n\n"
        "Up to 70% off + extra 10% off on fresh merchandise\n"
        "Covers men’s, women’s, and kids’ wear\n"
        "The listing is dated December 10–14, 2024, so it may be an older limited-time offer\n\n"
        "Monte Carlo\n\n"
        "Up to 50% off\n"
        "Specifically mentions items like sweaters and tracksuits, so this is the clearest winter-wear match\n\n"
        "Showoff\n\n"
        "An Independence Day offer is listed\n"
        "But the available content does not say it is winter-specific\n\n"
        "Best winter-clothing lead from the current floor content: Monte Carlo."
    ),
    "relatedFloors": [
        {"floor_id": "showoff", "label": "@showoff"},
        {"floor_id": "montecarlo", "label": "@montecarlo"},
        {"floor_id": "trends", "label": "@Trends"},
    ],
}


def _build_query_current_floor_document(*, preview_data: dict | None = None) -> str:
    preview_json = json.dumps(preview_data or {})
    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <style>
      * { box-sizing: border-box; }
      body { margin: 0; padding: 12px; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: #f6f7fb; color: #0f172a; }
      .card { border: 1px solid #e6e8ef; border-radius: 16px; background: #fff; box-shadow: 0 10px 28px rgba(16,24,40,.08); padding: 14px; }
      .title { font-size: 13px; color: #475569; margin-bottom: 8px; }
      .answer { white-space: pre-wrap; font-size: 14px; line-height: 1.5; color: #1f2937; }
      .footer { margin-top: 12px; padding-top: 10px; border-top: 1px solid #eef2f7; }
      .label { font-size: 12px; color: #64748b; margin-bottom: 6px; }
      .links { display: flex; flex-wrap: wrap; gap: 8px; }
      .link { font-size: 12px; text-decoration: none; border: 1px solid #e2e8f0; border-radius: 999px; padding: 6px 10px; color: #0f172a; background: #f8fafc; }
      .link:hover { background: #eef2ff; }
    </style>
  </head>
  <body>
    <section class=\"card\" aria-label=\"Query response\">
      <div class=\"title\">Floor answer</div>
      <div id=\"answer\" class=\"answer\">Here’s what I found.</div>
      <div id=\"footer\" class=\"footer\" style=\"display:none;\">
        <div class=\"label\">Related floors</div>
        <div id=\"links\" class=\"links\"></div>
      </div>
    </section>
    <script>
      const PREVIEW_DATA = {preview_json};
      const api = window.openai || {};
      const sc = Object.keys(PREVIEW_DATA).length
        ? PREVIEW_DATA
        : (window.structuredContent || window.__structuredContent || (api.toolOutput && api.toolOutput.structuredContent) || {});
      const answer = (sc.answer || '').trim() || 'Here’s what I found.';
      const related = Array.isArray(sc.relatedFloors) ? sc.relatedFloors : [];

      document.getElementById('answer').textContent = answer;

      if (related.length) {
        const footer = document.getElementById('footer');
        const links = document.getElementById('links');
        footer.style.display = 'block';
        related.slice(0, 4).forEach((row) => {
          const floorId = String(row.floor_id || row.floorUid || '').trim();
          if (!floorId) return;
          const label = String(row.label || row.floorName || floorId).trim();
          const a = document.createElement('a');
          a.className = 'link';
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.href = `https://${floorId}.xfloor.ai`;
          a.textContent = label.startsWith('@') ? label : `@${label}`;
          links.appendChild(a);
        });
        if (!links.children.length) {
          footer.style.display = 'none';
        }
      }
    </script>
  </body>
</html>"""


def build_query_current_floor_widget_html() -> str:
    return _build_query_current_floor_document()


def build_query_current_floor_preview_html() -> str:
    return _build_query_current_floor_document(preview_data=_SAMPLE_QUERY_DATA)
