/* Progressive browsing controls. Source data stays in the generated HTML. */
(() => {
  'use strict';

  const normalizePath = (path) => path.replace(/\/+$/, '') || '/';
  const currentPath = normalizePath(window.location.pathname);
  document.querySelectorAll('a[data-nav]').forEach((link) => {
    const path = normalizePath(new URL(link.href, window.location.href).pathname);
    if (path === currentPath) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });

  const scene = document.querySelector('[data-server-scene]');
  const explode = document.querySelector('[data-explode]');
  if (scene && explode) {
    explode.hidden = false;
    explode.addEventListener('click', () => {
      const expanded = scene.classList.toggle('is-exploded');
      explode.setAttribute('aria-pressed', String(expanded));
      const label = explode.querySelector('[data-explode-label]');
      if (label) label.textContent = expanded ? 'Collapse layers' : 'View layers';
    });
  }

  document.querySelectorAll('[data-catalog]').forEach((catalog) => {
    const grid = catalog.querySelector('[data-offer-grid]');
    if (!grid) return;
    const search = catalog.querySelector('input[data-search]');
    const provider = catalog.querySelector('select[data-provider]');
    const billing = catalog.querySelector('select[data-billing]');
    const sort = catalog.querySelector('select[data-sort]');
    const kinds = [...catalog.querySelectorAll('button[data-kind]')];
    const count = catalog.querySelector('[data-count]');
    const empty = catalog.querySelector('[data-empty]');
    const records = [...grid.querySelectorAll('article.offer-card')].map((card, index) => {
      const rawPrice = card.dataset.price;
      const price = rawPrice === undefined || rawPrice.trim() === '' ? NaN : Number(rawPrice);
      const rawOrder = Number(card.dataset.order);
      return {
        card,
        order: Number.isFinite(rawOrder) ? rawOrder : index,
        search: (card.dataset.searchText || card.dataset.title || card.textContent)
          .toLocaleLowerCase('en-US').replace(/\s+/g, ' '),
        price: Number.isFinite(price) && price >= 0 ? price : null,
        billing: card.dataset.billing || 'other',
      };
    });
    let kind = kinds.find((button) => button.getAttribute('aria-pressed') === 'true')?.dataset.kind || 'all';
    const billingOrder = { monthly: 0, annual: 1, other: 2 };

    const update = () => {
      const terms = (search?.value || '').trim().toLocaleLowerCase('en-US').split(/\s+/).filter(Boolean);
      const providerValue = provider?.value || 'all';
      const billingValue = billing?.value || 'all';
      const sortValue = sort?.value || 'default';
      let visible = 0;

      records.forEach((record) => {
        const data = record.card.dataset;
        const matches = terms.every((term) => record.search.includes(term))
          && (providerValue === 'all' || data.provider === providerValue)
          && (billingValue === 'all' || record.billing === billingValue)
          && (kind === 'all' || data.kind === kind);
        record.card.hidden = !matches;
        if (matches) visible += 1;
      });

      const sorted = [...records].sort((a, b) => {
        if (sortValue === 'default') return a.order - b.order;
        // Published monthly and annual amounts are not directly comparable.
        const group = (billingOrder[a.billing] ?? 2) - (billingOrder[b.billing] ?? 2);
        if (group) return group;
        if (a.billing === 'other' && b.billing === 'other') return a.order - b.order;
        if (a.price === null && b.price !== null) return 1;
        if (b.price === null && a.price !== null) return -1;
        if (a.price !== null && b.price !== null && a.price !== b.price) {
          return (sortValue === 'price-desc' ? -1 : 1) * (a.price - b.price);
        }
        return a.order - b.order;
      });
      sorted.forEach(({ card }) => grid.appendChild(card));

      kinds.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.kind === kind)));
      if (count) count.textContent = `${visible} of ${records.length} ${records.length === 1 ? 'offer' : 'offers'}`;
      if (empty) empty.hidden = visible !== 0 || records.length === 0;
    };

    search?.addEventListener('input', update);
    [provider, billing, sort].forEach((control) => control?.addEventListener('change', update));
    kinds.forEach((button) => button.addEventListener('click', () => {
      kind = button.dataset.kind;
      update();
    }));
    catalog.querySelectorAll('[data-reset]').forEach((button) => button.addEventListener('click', () => {
      if (search) search.value = '';
      if (provider) provider.value = 'all';
      if (billing) billing.value = 'all';
      if (sort) sort.value = 'default';
      kind = 'all';
      update();
      search?.focus({ preventScroll: true });
    }));

    update();
    catalog.querySelectorAll('[data-controls]').forEach((controls) => { controls.hidden = false; });
  });
})();
