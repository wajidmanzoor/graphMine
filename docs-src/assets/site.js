(() => {
  const base = new URL('../', document.currentScript.src);
  // Preserve catalog bookmarks from the former single-page site.
  if (!document.querySelector('#operation-grid') && location.pathname === base.pathname && /^#(?:family|problem)\//.test(location.hash)) {
    location.replace(new URL('problem/explorer/' + location.hash, base));
    return;
  }
  document.querySelector('.md-search[role=dialog]')?.setAttribute('aria-label', 'Search documentation');
  const menuToggle = document.querySelector('[data-doc-menu-toggle]');
  const drawer = document.querySelector('#__drawer');
  const navigation = document.querySelector('.md-sidebar--primary');
  if (menuToggle && drawer && navigation) {
    navigation.id = 'public-doc-navigation';
    const syncMenu = () => menuToggle.setAttribute('aria-expanded', String(drawer.checked));
    menuToggle.addEventListener('click', () => {
      drawer.checked = !drawer.checked;
      drawer.dispatchEvent(new Event('change', {bubbles: true}));
    });
    drawer.addEventListener('change', syncMenu);
    syncMenu();
  }
  document.querySelectorAll('#current-year').forEach(el => { el.textContent = new Date().getFullYear(); });
  const header = document.querySelector('[data-header]');
  window.addEventListener('scroll', () => header?.classList.toggle('scrolled', scrollY > 8), {passive:true});
  document.querySelector('.original-search-toggle')?.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.currentTarget.click(); }
  });
  const oldSections = {'#quickstart':'library/install/','#graph-format':'library/graph-format/','#cpp-api':'library/cpp-api/','#result-envelope':'library/outputs/'};
  if (location.pathname === base.pathname && oldSections[location.hash]) location.replace(new URL(oldSections[location.hash], base));
  const stats = document.querySelectorAll('[data-stat]');
  if (stats.length) fetch(new URL('catalog.json', base)).then(r => {
    if (!r.ok) throw new Error('Catalog unavailable');
    return r.json();
  }).then(c => stats.forEach(el => { el.textContent = c.counts[el.dataset.stat]; }))
    .catch(() => { stats.forEach(el => { el.textContent = 'See catalog'; }); });
  if (window.renderMathInElement) renderMathInElement(document.body, {
    delimiters: [{left:'\\(',right:'\\)',display:false},{left:'\\[',right:'\\]',display:true}],
    throwOnError: false
  });
})();
