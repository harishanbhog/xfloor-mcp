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
  var data = readData();
  var root = document.getElementById('root');
  if (!root) return;
  var blocks = Array.isArray(data.blocks) ? data.blocks.slice(0, 6) : [];
  var title = data.floor_title || data.floor_ref || 'xFloor';
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
})();
