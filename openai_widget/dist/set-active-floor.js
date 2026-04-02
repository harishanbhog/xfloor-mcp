(function () {
  function parseUiMessage(raw) {
    var data = typeof raw === 'string' ? parseJson(raw) : raw;
    if (!data || typeof data !== 'object') return null;
    if (data.jsonrpc !== '2.0' || typeof data.method !== 'string' || data.method.indexOf('ui/') !== 0) return null;
    var params = data.params && typeof data.params === 'object' ? data.params : {};
    if (params.structuredContent && typeof params.structuredContent === 'object') return params.structuredContent;
    if (params.result && typeof params.result === 'object' && params.result.structuredContent && typeof params.result.structuredContent === 'object') return params.result.structuredContent;
    if (data.result && typeof data.result === 'object' && data.result.structuredContent && typeof data.result.structuredContent === 'object') return data.result.structuredContent;
    return null;
  }
  function parseJson(value) {
    try { return JSON.parse(value); } catch (_e) { return null; }
  }
  function readCompatibilityData() {
    try {
      var node = document.getElementById('widget-preview-data');
      if (node && node.textContent && node.textContent.trim() && node.textContent.trim() !== '{}') {
        return JSON.parse(node.textContent);
      }
    } catch (_e) {}
    var api = window.openai || {};
    return window.structuredContent || window.__structuredContent || (api.toolOutput && api.toolOutput.structuredContent) || {};
  }
  function render(data) {
    var root = document.getElementById('root');
    if (!root) return;
    if (!data || typeof data !== 'object' || !Object.keys(data).length) {
      root.innerHTML = '<section class="card"><div class="answer">No floor data yet.</div></section>';
      return;
    }
    var blocks = Array.isArray(data.blocks) ? data.blocks.slice(0, 6) : [];
    var title = data.floor_title || data.floor_ref || 'Active floor';
    var floorRef = data.floor_ref ? '@' + String(data.floor_ref).replace(/^@/, '') : '';
    var floorUrl = data.floor_id ? 'https://' + data.floor_id + '.xfloor.ai' : '';
    var chips = blocks.map(function (b) { return '<span class="chip">' + (b && (b.name || b.block_id) || 'Unnamed') + '</span>'; }).join('');
    root.innerHTML =
      '<section class="card">' +
        '<div class="row">' +
        (data.floor_logo_url ? '<img class="logo" src="' + data.floor_logo_url + '" alt="floor logo" />' : '') +
        '<div><h1 class="title">' + title + '</h1>' + (floorRef ? '<div>' + floorRef + '</div>' : '') + '</div>' +
        '</div>' +
        (data.floor_description ? '<p class="desc">' + data.floor_description + '</p>' : '') +
        (chips ? '<div class="chips">' + chips + '</div>' : '') +
        (floorUrl ? '<p style="margin-top:12px"><a class="link" href="' + floorUrl + '" target="_blank" rel="noreferrer">Open floor</a></p>' : '') +
      '</section>';
  }
  window.addEventListener('message', function (event) {
    var payload = parseUiMessage(event.data);
    if (payload) render(payload);
  });
  render(readCompatibilityData() || {});
})();
