const navItems = [
  ['discover', 'Discover', 'job-discovery.html'],
  ['saved', 'Saved', 'saved-jobs.html'],
  ['tracker', 'Tracker', 'application-tracker.html'],
  ['notifications', 'Inbox', 'notifications.html'],
  ['preferences', 'Preferences', 'preferences.html'],
  ['admin', 'Review', 'duplicate-review.html'],
];

function renderNavigation() {
  const host = document.querySelector('[data-app-nav]');
  if (!host) return;
  const active = host.dataset.appNav;
  host.innerHTML = `
    <a class="skip-link" href="#main-content">Skip to content</a>
    <header class="app-header">
      <div class="app-nav-shell">
        <a class="app-wordmark" href="index.html" aria-label="Hunt Board concept home">
          <svg viewBox="0 0 40 40" aria-hidden="true">
            <rect x="1" y="1" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2"></rect>
            <circle cx="20" cy="20" r="9" fill="none" stroke="currentColor"></circle>
            <path d="M20 5v7M20 28v7M5 20h7M28 20h7" fill="none" stroke="currentColor"></path>
            <path d="m23.5 12.5-2 9-5 6 2-9 5-6Z" fill="#e4572e" stroke="currentColor"></path>
          </svg>
          <span class="app-wordmark-copy"><strong>Hunt Board</strong><small>Job-search field desk</small></span>
        </a>
        <button class="menu-toggle" type="button" aria-expanded="false" aria-controls="app-navigation"><span class="sr-only">Open navigation</span>☰</button>
        <nav class="app-nav" id="app-navigation" aria-label="Product mockup navigation">
          ${navItems.map(([key, label, href]) => `<a href="${href}"${active === key ? ' aria-current="page"' : ''}>${label}${key === 'notifications' ? '<span class="nav-badge">3</span>' : ''}</a>`).join('')}
        </nav>
      </div>
    </header>`;
  const toggle = host.querySelector('.menu-toggle');
  const nav = host.querySelector('.app-nav');
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!open));
    nav.classList.toggle('is-open', !open);
  });
}

function makeToast(message) {
  document.querySelector('.toast')?.remove();
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.setAttribute('role', 'status');
  toast.textContent = message;
  document.body.append(toast);
  window.setTimeout(() => toast.remove(), 2600);
}

function setupFilterButtons(container, items, callback) {
  const buttons = [...container.querySelectorAll('[data-filter]')];
  buttons.forEach((button) => button.addEventListener('click', () => {
    buttons.forEach((item) => item.setAttribute('aria-pressed', 'false'));
    button.setAttribute('aria-pressed', 'true');
    callback(button.dataset.filter, items);
  }));
}

function setupDiscovery() {
  const ledger = document.querySelector('[data-discovery-ledger]');
  if (!ledger) return;
  const rows = [...ledger.querySelectorAll('tbody tr')];
  const drawer = document.querySelector('[data-observation-drawer]');
  const closeButton = drawer.querySelector('[data-close-drawer]');
  const fields = {};
  drawer.querySelectorAll('[data-job-field]').forEach((node) => {
    fields[node.dataset.jobField] ||= [];
    fields[node.dataset.jobField].push(node);
  });

  function openRow(row) {
    rows.forEach((item) => {
      item.classList.toggle('is-selected', item === row);
      item.setAttribute('aria-selected', String(item === row));
      const status = item.querySelector('[data-row-status]');
      if (status) {
        status.textContent = item === row ? 'Viewing' : status.dataset.original;
        status.className = `status ${item === row ? 'status-viewing' : status.dataset.class}`;
      }
    });
    ['title', 'company', 'location', 'source', 'workType', 'level', 'freshness', 'score'].forEach((name) => {
      fields[name]?.forEach((node) => { node.textContent = row.dataset[name]; });
    });
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('drawer-open');
    closeButton.focus();
  }

  function closeDrawer() {
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('drawer-open');
    const selected = ledger.querySelector('.is-selected');
    if (selected) {
      const status = selected.querySelector('[data-row-status]');
      if (status) {
        status.textContent = status.dataset.original;
        status.className = `status ${status.dataset.class}`;
      }
      selected.classList.remove('is-selected');
      selected.setAttribute('aria-selected', 'false');
      selected.focus();
    }
  }

  rows.forEach((row) => {
    row.addEventListener('click', (event) => {
      if (event.target.closest('button, a')) event.preventDefault();
      openRow(row);
    });
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openRow(row); }
    });
    const status = row.querySelector('[data-row-status]');
    if (status) status.dataset.class = [...status.classList].find((name) => name.startsWith('status-')) || '';
  });
  closeButton.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && drawer.classList.contains('is-open')) closeDrawer(); });

  const search = document.querySelector('[data-ledger-search]');
  let activeFilter = 'all';
  function applyLedgerFilters() {
    const term = search.value.trim().toLowerCase();
    rows.forEach((row) => {
      const matchesText = row.dataset.search.includes(term);
      const matchesFilter = activeFilter === 'all' || row.dataset.state === activeFilter || (activeFilter === 'top' && Number(row.dataset.score) >= 90);
      row.hidden = !(matchesText && matchesFilter);
    });
    const visible = rows.filter((row) => !row.hidden).length;
    document.querySelector('[data-results-count]').textContent = `${visible} sightings shown`;
  }
  search.addEventListener('input', applyLedgerFilters);
  setupFilterButtons(document.querySelector('[data-ledger-filters]'), rows, (filter) => { activeFilter = filter; applyLedgerFilters(); });
  drawer.querySelector('[data-save-job]').addEventListener('click', (event) => {
    event.currentTarget.textContent = 'Saved to field board';
    makeToast('Job saved to your field board.');
  });
}

function setupCardSearch(sectionSelector, inputSelector, itemSelector) {
  const section = document.querySelector(sectionSelector);
  const input = document.querySelector(inputSelector);
  if (!section || !input) return;
  const items = [...section.querySelectorAll(itemSelector)];
  input.addEventListener('input', () => {
    const term = input.value.toLowerCase().trim();
    items.forEach((item) => { item.hidden = !item.dataset.search.includes(term); });
  });
}

function setupTracker() {
  const table = document.querySelector('[data-tracker]');
  if (!table) return;
  const rows = [...table.querySelectorAll('.film-row')];
  const search = document.querySelector('[data-tracker-search]');
  const stage = document.querySelector('[data-stage-filter]');
  const status = document.querySelector('[data-status-filter]');
  const date = document.querySelector('[data-date-filter]');
  function filter() {
    const term = search.value.toLowerCase().trim();
    rows.forEach((row) => {
      const matches = row.dataset.search.includes(term)
        && (stage.value === 'all' || row.dataset.stage === stage.value)
        && (status.value === 'all' || row.dataset.status === status.value)
        && (date.value === 'all' || row.dataset.date === date.value);
      row.hidden = !matches;
    });
    document.querySelector('[data-tracker-count]').textContent = `${rows.filter((row) => !row.hidden).length} applications shown`;
  }
  [search, stage, status, date].forEach((control) => control.addEventListener(control === search ? 'input' : 'change', filter));
  document.querySelector('[data-add-application]').addEventListener('click', () => makeToast('Static preview: application form would open here.'));

  table.querySelectorAll('[data-edit-field]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.querySelector('.film-edit-control')) return;

      const field = button.dataset.editField;
      const company = button.dataset.company;
      const currentValue = button.dataset.value;
      const valueNode = button.querySelector('strong');
      const originalMarkup = valueNode.innerHTML;
      let control;

      if (field === 'stage') {
        control = document.createElement('select');
        ['Saved', 'Applied', 'Interview', 'Offer', 'Closed'].forEach((optionValue) => {
          const option = document.createElement('option');
          option.value = optionValue;
          option.textContent = optionValue;
          option.selected = optionValue === currentValue;
          control.append(option);
        });
      } else {
        control = document.createElement('input');
        control.type = 'text';
        control.value = currentValue;
      }

      control.className = 'film-edit-control';
      control.setAttribute('aria-label', `Update ${field} for ${company}`);
      valueNode.replaceChildren(control);
      control.focus();
      if (control.select) control.select();

      let finished = false;
      function finish(save) {
        if (finished) return;
        finished = true;
        const nextValue = control.value.trim();
        if (!save || !nextValue) {
          valueNode.innerHTML = originalMarkup;
          return;
        }

        button.dataset.value = nextValue;
        if (field === 'stage') {
          const row = button.closest('.film-row');
          row.dataset.stage = nextValue.toLowerCase();
          const tag = document.createElement('span');
          tag.className = `stage-tag${nextValue === 'Interview' ? ' stage-interview' : ''}${nextValue === 'Offer' ? ' stage-offer' : ''}`;
          tag.textContent = nextValue;
          valueNode.replaceChildren(tag);
          filter();
        } else {
          valueNode.textContent = nextValue;
        }
        makeToast(`${company} ${field} updated in this static preview.`);
      }

      control.addEventListener('click', (event) => event.stopPropagation());
      control.addEventListener('change', () => field === 'stage' && finish(true));
      control.addEventListener('blur', () => finish(true));
      control.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') finish(true);
        if (event.key === 'Escape') finish(false);
      });
    });
  });
}

function setupInbox() {
  const list = document.querySelector('[data-dispatch-list]');
  const tabs = document.querySelector('[data-inbox-tabs]');
  if (!list || !tabs) return;
  const items = [...list.querySelectorAll('.dispatch-item')];
  setupFilterButtons(tabs, items, (filter) => items.forEach((item) => { item.hidden = filter !== 'all' && item.dataset.kind !== filter; }));
  list.addEventListener('click', (event) => {
    const readButton = event.target.closest('[data-mark-read]');
    if (readButton) {
      const item = readButton.closest('.dispatch-item');
      item.classList.remove('is-unread');
      readButton.remove();
      makeToast('Dispatch marked as read.');
    }
  });
  document.querySelector('[data-mark-all]').addEventListener('click', () => {
    items.forEach((item) => item.classList.remove('is-unread'));
    list.querySelectorAll('[data-mark-read]').forEach((button) => button.remove());
    makeToast('All dispatches marked as read.');
  });
}

function setupPreferences() {
  const form = document.querySelector('[data-preferences-form]');
  if (!form) return;
  form.addEventListener('submit', (event) => { event.preventDefault(); makeToast('Preferences saved in this static preview.'); });
  form.addEventListener('reset', () => window.setTimeout(() => makeToast('Preview preferences reset.'), 0));
}

function setupAdmin() {
  const comparison = document.querySelector('[data-comparison]');
  if (!comparison) return;
  comparison.addEventListener('click', (event) => {
    const decision = event.target.closest('[data-decision]');
    if (!decision) return;
    const label = decision.dataset.decision;
    document.querySelector('[data-decision-note]').textContent = `Decision recorded: ${label}. Loading next review case…`;
    makeToast(`Duplicate review marked “${label}”.`);
  });
  document.querySelectorAll('.queue-item').forEach((item) => item.addEventListener('click', () => {
    document.querySelectorAll('.queue-item').forEach((other) => other.classList.remove('is-active'));
    item.classList.add('is-active');
    makeToast('Static preview: review case selected.');
  }));
}

renderNavigation();
setupDiscovery();
setupCardSearch('[data-saved-board]', '[data-saved-search]', '.wanted-card');
setupTracker();
setupInbox();
setupPreferences();
setupAdmin();
