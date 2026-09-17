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
  var nav = document.getElementById('studio-sidebar-nav');
  var navApi = window.studioNav;
  function navStorage() {
    try {
      return window.localStorage;
    } catch (error) {
      return null;
    }
  }
  if (nav && navApi) {
    var activeSection = nav.getAttribute('data-studio-active-section') || '';
    var preferences = navApi.readPreferences(navStorage());
    nav.querySelectorAll('[data-studio-section-toggle]').forEach(function (button) {
      var key = button.getAttribute('data-studio-section-key') || '';
      var panel = document.getElementById(button.getAttribute('aria-controls') || '');
      if (!panel) return;
      function apply(expanded) {
        button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        panel.hidden = !expanded;
        var chevron = button.querySelector('.studio-section-chevron');
        if (chevron) chevron.classList.toggle('-rotate-90', !expanded);
      }
      var rendered = button.getAttribute('aria-expanded') === 'true';
      apply(navApi.resolveExpanded(preferences, key, rendered, activeSection));
      button.addEventListener('click', function (event) {
        event.preventDefault();
        var next = button.getAttribute('aria-expanded') !== 'true';
        preferences[key] = next;
        navApi.writePreference(navStorage(), key, next);
        apply(navApi.resolveExpanded(preferences, key, next, activeSection));
      });
    });
  }
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
    function resultRow(item) {
      var link = document.createElement('a');
      link.href = item.url;
      link.className = 'block px-3 py-2 text-sm hover:bg-secondary';
      var label = document.createElement('span');
      label.className = 'block truncate text-foreground';
      label.textContent = item.label;
      link.appendChild(label);
      if (item.summary) {
        var summary = document.createElement('span');
        summary.className = 'block truncate text-xs text-muted-foreground';
        summary.textContent = item.summary;
        link.appendChild(summary);
      }
      return link;
    }
    function searchGroups(payload) {
      if (navApi && navApi.searchGroups) return navApi.searchGroups(payload);
      // studio-nav.js is missing: still show every result, headed by the raw group name.
      var groups = (payload && payload.results) || {};
      return Object.keys(groups)
        .map(function (key) {
          return {key: key, label: key, items: groups[key] || []};
        })
        .filter(function (group) {
          return group.items.length > 0;
        });
    }
    function render(payload) {
      results.replaceChildren();
      searchGroups(payload).forEach(function (group) {
        var block = document.createElement('section');
        block.className = 'border-b border-border last:border-b-0';
        block.setAttribute('data-studio-search-group', group.key);
        var heading = document.createElement('h3');
        heading.className =
          'px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground';
        heading.textContent = group.label;
        block.appendChild(heading);
        group.items.forEach(function (item) {
          block.appendChild(resultRow(item));
        });
        results.appendChild(block);
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
  document.querySelectorAll('[data-studio-theme-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      var dark = document.documentElement.classList.toggle('dark');
      button.setAttribute('aria-pressed', dark ? 'true' : 'false');
      var storage = navStorage();
      try {
        if (storage) storage.setItem('theme', dark ? 'dark' : 'light');
      } catch (error) {
        // Storage may be blocked; the theme still applies to this page view.
      }
    });
  });
  if (window.lucide) window.lucide.createIcons();
})();
