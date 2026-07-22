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

export function loading(target, message = 'Reading field records…') {
  target.replaceChildren(element('div', { className: 'loading-state', role: 'status', text: message }));
}
