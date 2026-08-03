export function makeToast(message, type = 'success') {
  document.querySelector('.toast')?.remove();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.textContent = message;
  document.body.append(toast);
  window.setTimeout(() => toast.remove(), 3600);
}

export function setBusy(element, isBusy) {
  if (!element) return;
  element.toggleAttribute('disabled', isBusy);
  element.setAttribute('aria-busy', String(isBusy));
}

export function renderEmpty(target, title, body, action) {
  target.replaceChildren();
  const section = document.createElement('section');
  section.className = 'empty-state state-panel';
  section.setAttribute('role', 'status');
  const heading = document.createElement('h2');
  heading.textContent = title;
  const copy = document.createElement('p');
  copy.textContent = body;
  section.append(heading, copy);
  if (action) section.append(action);
  target.append(section);
}

export function renderError(target, error, retry) {
  target.replaceChildren();
  const section = document.createElement('section');
  section.className = 'empty-state state-panel state-error';
  section.setAttribute('role', 'alert');
  const heading = document.createElement('h2');
  heading.textContent = 'The field report could not be loaded';
  const copy = document.createElement('p');
  copy.textContent = error?.message || 'An unknown server error occurred.';
  section.append(heading, copy);
  if (retry) {
    const button = document.createElement('button');
    button.className = 'button';
    button.type = 'button';
    button.textContent = 'Try again';
    button.addEventListener('click', retry);
    section.append(button);
  }
  target.append(section);
}

export function debounce(fn, ms = 300) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), ms);
  };
}

export function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(options).forEach(([key, value]) => {
    if (key === 'className') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  });
  node.append(...(Array.isArray(children) ? children : [children]));
  return node;
}

function skeletonKind(target, requested) {
  if (requested !== 'auto') return requested;
  if (target.matches('[data-detail], [data-dialog-content], [data-comparison]')) return 'dossier';
  if (target.matches('[data-board], [data-search-list], [data-source-board]')) return 'cards';
  if (target.matches('[data-results], [data-tracker], [data-run-list], [data-list], [data-queue]')) return 'ledger';
  return 'panel';
}

export function loading(target, message = 'Reading field records…', variant = 'auto') {
  const kind = skeletonKind(target, variant);
  const state = element('div', {
    className: `skeleton-state skeleton-${kind}`,
    role: 'status',
    'aria-label': message,
  });
  state.append(element('span', { className: 'sr-only', text: message }));
  const count = kind === 'dossier' ? 2 : kind === 'cards' ? 3 : kind === 'ledger' ? 5 : 1;
  for (let index = 0; index < count; index += 1) {
    const item = element('div', { className: 'skeleton-item', 'aria-hidden': 'true' });
    item.append(
      element('i', { className: 'skeleton-line skeleton-line-label' }),
      element('i', { className: 'skeleton-line skeleton-line-title' }),
      element('i', { className: 'skeleton-line skeleton-line-copy' }),
      element('i', { className: 'skeleton-line skeleton-line-short' }),
    );
    state.append(item);
  }
  target.replaceChildren(state);
}
