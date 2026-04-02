(function () {
  function readData() {
    try {
      var node = document.getElementById('widget-preview-data');
      if (node && node.textContent && node.textContent.trim() && node.textContent.trim() !== '{}') {
        return JSON.parse(node.textContent);
      }
    } catch (_e) {}
    var api = window.openai || {};
    return window.structuredContent || window.__structuredContent || (api.toolOutput && api.toolOutput.structuredContent) || {};
  }
  function hasData(value) {
    return !!(value && typeof value === 'object' && Object.keys(value).length);
  }
  function render(data) {
    var root = document.getElementById('root');
    if (!root) return;
    var answer = (data.answer || '').trim() || "Here's what I found.";
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
  var attempts = 0;
  var maxAttempts = 60;
  var intervalMs = 100;
  (function hydrate() {
    var data = readData();
    if (hasData(data) || attempts >= maxAttempts) {
      render(data || {});
      return;
    }
    attempts += 1;
    setTimeout(hydrate, intervalMs);
  })();
})();
