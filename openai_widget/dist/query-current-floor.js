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
      root.innerHTML = '<section class="card"><div class="answer">No query result yet.</div></section>';
      return;
    }
    var answer = (data.answer || '').trim();
    var related = Array.isArray(data.relatedFloors) ? data.relatedFloors.slice(0, 6) : [];
    var links = related.map(function (item) {
      var floorId = String((item && item.floor_id) || '').trim();
      if (!floorId) return '';
      var label = String((item && (item.label || item.floorName || floorId)) || '').trim();
      if (!label) return '';
      if (label.charAt(0) !== '@') label = '@' + label;
      return '<a class="link" href="https://' + floorId + '.xfloor.ai" target="_blank" rel="noreferrer">' + label + '</a>';
    }).join('');
    root.innerHTML = '<section class="card"><div class="answer">' + answer + '</div>' + (links ? '<div class="links">' + links + '</div>' : '') + '</section>';
  }
  window.addEventListener('message', function (event) {
    var payload = parseUiMessage(event.data);
    if (payload) render(payload);
  });
  render(readCompatibilityData() || {});
})();
