if (window.katex) {
  document.querySelectorAll('.tex-equation').forEach(function (equation) {
    window.katex.render(equation.dataset.tex, equation, { displayMode: true, throwOnError: false });
  });
}

// Preserve direct links into any section while showing one part of the guide at a time.
(function () {
  var groups = ['methode', 'donnees'];
  var links = document.querySelectorAll('[data-section-link]');
  function show(group) {
    document.querySelectorAll('[data-guide-group]').forEach(function (el) { el.hidden = el.dataset.guideGroup !== group; });
    document.querySelectorAll('[data-nav-group]').forEach(function (el) { el.hidden = el.dataset.navGroup !== group; });
    links.forEach(function (el) { if (el.dataset.sectionLink === group) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current'); });
  }
  function sync() {
    var hash = decodeURIComponent(location.hash.slice(1));
    var target = document.getElementById(hash);
    var section = target && target.closest('[data-guide-group]');
    show(groups.includes(hash) ? hash : section ? section.dataset.guideGroup : 'methode');
    if (section) requestAnimationFrame(function () { target.scrollIntoView(); });
  }
  links.forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      var group = link.dataset.sectionLink;
      if (location.hash !== '#' + group) history.pushState(null, '', '#' + group);
      show(group);
    });
  });
  window.addEventListener('hashchange', sync);
  sync();
})();
