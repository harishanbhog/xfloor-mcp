"""OpenAI widget HTML templates."""


def build_floor_summary_widget_html() -> str:
    return """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <style>
      body { font-family: system-ui, sans-serif; margin: 0; padding: 10px; color: #111; background: #f8fafc; }
      .card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 12px; background: #fff; }
      .top { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
      .logo { width: 44px; height: 44px; border-radius: 8px; object-fit: cover; border: 1px solid #e5e7eb; display: none; }
      .title { font-weight: 700; font-size: 14px; line-height: 1.2; }
      .handle { font-size: 12px; color: #6b7280; margin-top: 2px; }
      .desc { font-size: 13px; line-height: 1.4; color: #1f2937; margin: 8px 0 10px 0; white-space: pre-wrap; }
      .subhead { font-size: 12px; color: #374151; font-weight: 600; margin-bottom: 6px; }
      .blocks { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
      .block { border: 1px solid #eef2f7; border-radius: 8px; padding: 8px; }
      .block-name { font-size: 12px; font-weight: 600; color: #111827; }
      .block-meta { font-size: 12px; color: #6b7280; margin-top: 2px; }
      .empty { font-size: 12px; color: #6b7280; }
      .footer { margin-top: 10px; font-size: 12px; }
      a { color: #2563eb; text-decoration: none; }
      a:hover { text-decoration: underline; }
    </style>
  </head>
  <body>
    <div class=\"card\">
      <div class=\"top\">
        <img class=\"logo\" id=\"logo\" alt=\"Floor logo\" />
        <div>
          <div class=\"title\" id=\"title\">xFloor</div>
          <div class=\"handle\" id=\"handle\">@floor</div>
        </div>
      </div>
      <div class=\"desc\" id=\"desc\">No description.</div>
      <div class=\"subhead\">Blocks</div>
      <ul class=\"blocks\" id=\"blocks\"></ul>
      <div class=\"empty\" id=\"blocks-empty\" style=\"display:none;\">No blocks available.</div>
      <div class=\"footer\" id=\"footer\"></div>
    </div>
    <script>
      const api = window.openai || {};
      const sc = (window.structuredContent || window.__structuredContent || api?.toolOutput?.structuredContent || {});
      const floorId = sc.floor_id || "";
      const floorRef = sc.floor_ref || floorId || "floor";
      const floorTitle = sc.floor_title || floorRef;
      const floorDescription = sc.floor_description || "No description available.";
      const logoUrl = sc.floor_logo_url || "";
      const blocks = Array.isArray(sc.blocks) ? sc.blocks : [];

      document.getElementById("title").textContent = floorTitle;
      document.getElementById("handle").textContent = "@" + String(floorRef).replace(/^@/, "");
      document.getElementById("desc").textContent = floorDescription;
      const logoEl = document.getElementById("logo");
      if (logoUrl) {
        logoEl.src = logoUrl;
        logoEl.style.display = "block";
      }

      const listEl = document.getElementById("blocks");
      const emptyEl = document.getElementById("blocks-empty");
      if (!blocks.length) {
        emptyEl.style.display = "block";
      } else {
        blocks.slice(0, 8).forEach((block) => {
          const li = document.createElement("li");
          li.className = "block";
          const name = block.name || block.block_id || "Unnamed block";
          const type = block.type ? " (" + block.type + ")" : "";
          const desc = block.description || "";
          li.innerHTML = '<div class=\"block-name\">' + name + type + '</div>' + (desc ? '<div class=\"block-meta\">' + desc + '</div>' : '');
          listEl.appendChild(li);
        });
      }
      if (floorId) {
        const url = "https://" + floorId + ".xfloor.ai";
        document.getElementById("footer").innerHTML = '<a href="' + url + '" target="_blank" rel="noopener noreferrer">Open active floor</a>';
      } else {
        document.getElementById("footer").textContent = "";
      }
    </script>
  </body>
</html>"""
