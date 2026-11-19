(() => {
  const base = new URL('../', document.currentScript.src);
  // Preserve catalog bookmarks from the former single-page site.
  if (location.pathname === base.pathname && /^#(?:family|problem)\//.test(location.hash)) {
    location.replace(new URL('problem/explorer/' + location.hash, base));
    return;
  }
  document.querySelector('.md-search[role=dialog]')?.setAttribute('aria-label', 'Search documentation');
  const stats = document.querySelectorAll('[data-stat]');
  if (stats.length) fetch(new URL('catalog.json', base)).then(r => {
    if (!r.ok) throw new Error('Catalog unavailable');
    return r.json();
  }).then(c => stats.forEach(el => { el.textContent = c.counts[el.dataset.stat]; }))
    .catch(() => { document.querySelector('.catalog-counts').textContent = 'Browse the catalog for current coverage.'; });
  if (window.renderMathInElement) renderMathInElement(document.body, {
    delimiters: [{left:'\\(',right:'\\)',display:false},{left:'\\[',right:'\\]',display:true}],
    throwOnError: false
  });
})();
