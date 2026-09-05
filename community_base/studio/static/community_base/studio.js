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
  if (window.lucide) window.lucide.createIcons();
})();

