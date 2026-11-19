(() => {
  const index = document.querySelector('[data-native-index]');
  if (!index) return;
  const search = document.querySelector('#native-function-search');
  const group = document.querySelector('#native-function-group');
  const status = document.querySelector('#native-index-status');
  const more = document.querySelector('#native-show-more');
  const rows = [...index.querySelectorAll('[data-function]')];
  const pageSize = 40;
  let limit = pageSize;
  const render = () => {
    const terms = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let found = 0;
    for (const row of rows) {
      const matches = (!group.value || row.dataset.group === group.value) && terms.every(term => row.dataset.function.includes(term));
      row.hidden = !matches || ++found > limit;
    }
    status.textContent = found ? `Showing ${Math.min(found, limit)} of ${found} matching functions.` : 'No matching functions. Try a name, parameter, or source file.';
    more.hidden = found <= limit;
  };
  search.addEventListener('input', () => { limit = pageSize; render(); });
  group.addEventListener('change', () => { limit = pageSize; render(); });
  more.addEventListener('click', () => { limit += pageSize; render(); });
  render();
})();
