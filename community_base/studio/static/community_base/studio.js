(function () {
  var sidebar = document.getElementById('studio-sidebar');
  var backdrop = document.getElementById('studio-backdrop');
  var openButton = document.getElementById('studio-sidebar-toggle');
  var closeButton = document.getElementById('studio-sidebar-close');
  function setOpen(open) {
    if (!sidebar || !backdrop || !openButton) return;
    sidebar.classList.toggle('hidden', !open);
    backdrop.classList.toggle('hidden', !open);
    openButton.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  if (openButton) openButton.addEventListener('click', function () { setOpen(true); });
  if (closeButton) closeButton.addEventListener('click', function () { setOpen(false); });
  if (backdrop) backdrop.addEventListener('click', function () { setOpen(false); });
  document.querySelectorAll('details[data-studio-overflow][open]').forEach(function (menu) {
    document.addEventListener('click', function (event) {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });
  document.querySelectorAll('[data-studio-search]').forEach(function (root) {
    var input = root.querySelector('input[type="search"]');
    var results = root.querySelector('[id$="-results"]');
    var endpoint = root.getAttribute('data-endpoint');
    function closeResults() {
      results.classList.add('hidden');
      input.setAttribute('aria-expanded', 'false');
    }
    function showMessage(message) {
      results.replaceChildren();
      var row = document.createElement('p');
      row.className = 'px-3 py-2 text-sm text-muted-foreground';
      row.textContent = message;
      results.appendChild(row);
      results.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }
    function render(payload) {
      results.replaceChildren();
      Object.keys(payload.results || {}).forEach(function (group) {
        (payload.results[group] || []).forEach(function (item) {
          var link = document.createElement('a');
          link.href = item.url;
          link.className = 'block px-3 py-2 text-sm hover:bg-secondary';
          link.textContent = item.label;
          results.appendChild(link);
        });
      });
      if (!results.children.length) return showMessage('No results');
      results.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }
    input.addEventListener('input', function () {
      var query = input.value.trim();
      if (query.length < 2) return closeResults();
      fetch(endpoint + '?q=' + encodeURIComponent(query), {
        credentials: 'same-origin',
        headers: {Accept: 'application/json'}
      }).then(function (response) {
        if (!response.ok) throw new Error('Search failed');
        return response.json();
      }).then(render).catch(function () { showMessage('Search unavailable'); });
    });
    document.addEventListener('click', function (event) {
      if (!root.contains(event.target)) closeResults();
    });
    document.addEventListener('keydown', function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        input.focus();
      } else if (event.key === 'Escape') {
        closeResults();
      }
    });
  });
  if (window.lucide) window.lucide.createIcons();
})();
