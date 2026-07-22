import { api } from './api.js?v=20260721-1';

const navItems = [
  ['discover', 'Discover', '/app/job-discovery.html'],
  ['saved', 'Saved', '/app/saved-jobs.html'],
  ['tracker', 'Tracker', '/app/application-tracker.html'],
  ['notifications', 'Inbox', '/app/notifications.html'],
  ['preferences', 'Preferences', '/app/preferences.html'],
  ['admin', 'Review', '/app/duplicate-review.html'],
];

export function renderNavigation() {
  const host = document.querySelector('[data-app-nav]');
  if (!host) return;
  const active = host.dataset.appNav;
  host.replaceChildren();
  const skip = document.createElement('a');
  skip.className = 'skip-link';
  skip.href = '#main-content';
  skip.textContent = 'Skip to content';
  const header = document.createElement('header');
  header.className = 'app-header';
  header.innerHTML = `<div class="app-nav-shell">
    <a class="app-wordmark" href="/app/" aria-label="Hunt Board home">
      <svg viewBox="0 0 40 40" aria-hidden="true"><rect x="1" y="1" width="38" height="38" fill="none" stroke="currentColor" stroke-width="2"></rect><circle cx="20" cy="20" r="9" fill="none" stroke="currentColor"></circle><path d="M20 5v7M20 28v7M5 20h7M28 20h7" fill="none" stroke="currentColor"></path><path d="m23.5 12.5-2 9-5 6 2-9 5-6Z" fill="#e4572e" stroke="currentColor"></path></svg>
      <span class="app-wordmark-copy"><strong>Hunt Board</strong><small>Job-search field desk</small></span>
    </a>
    <button class="menu-toggle" type="button" aria-expanded="false" aria-controls="app-navigation"><span class="sr-only">Open navigation</span>☰</button>
    <nav class="app-nav" id="app-navigation" aria-label="Product navigation"></nav>
  </div>`;
  const nav = header.querySelector('nav');
  navItems.forEach(([key, label, href]) => {
    const link = document.createElement('a');
    link.href = href;
    if (active === key) link.setAttribute('aria-current', 'page');
    link.append(document.createTextNode(label));
    if (key === 'notifications') {
      const badge = document.createElement('span');
      badge.className = 'nav-badge';
      badge.dataset.unreadBadge = '';
      badge.hidden = true;
      link.append(badge);
    }
    nav.append(link);
  });
  host.append(skip, header);
  const toggle = header.querySelector('.menu-toggle');
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!open));
    nav.classList.toggle('is-open', !open);
  });
  observePageIntro();
  refreshUnreadCount();
}

export function decoratePageIntro() {
  const intro = document.querySelector('.page-intro');
  if (!intro) return false;
  if (intro.querySelector('.field-motif')) return true;
  const motif = document.createElement('div');
  motif.className = 'field-motif';
  motif.setAttribute('aria-hidden', 'true');
  motif.innerHTML = `<svg viewBox="0 0 420 150">
    <g class="motif-acacia"><path d="M92 139c5-35 3-61-7-91m8 91c4-34 18-58 42-88M89 82 56 48m41 17 12-42"></path><ellipse cx="91" cy="34" rx="61" ry="17"></ellipse><ellipse cx="47" cy="51" rx="40" ry="15"></ellipse><ellipse cx="139" cy="52" rx="44" ry="15"></ellipse><ellipse cx="92" cy="58" rx="74" ry="17"></ellipse></g>
    <g class="motif-camera" transform="translate(230 76)"><rect x="0" y="12" width="70" height="44"></rect><path d="M12 12 20 0h22l8 12"></path><circle cx="36" cy="34" r="14"></circle><path d="M59 22h5"></path></g>
    <g class="motif-binoculars" transform="translate(326 76)"><path d="M13 8h16l7 18v25H3V26Zm45 0H42l-7 18v25h33V26Z"></path><circle cx="19" cy="45" r="14"></circle><circle cx="52" cy="45" r="14"></circle><path d="M29 15h13"></path></g>
    <path class="motif-grass" d="M0 148 8 115m4 33 9-22m9 22-2-37m14 37 8-28m8 28 5-39m15 39 8-24m12 24-1-33m15 33 7-27m13 27 9-39m14 39 8-25m13 25-2-35m16 35 9-29m13 29 7-40m16 40 8-26m14 26-1-34m15 34 8-23m12 23 8-39m15 39 9-27m11 27-2-34m15 34 8-25m12 25 7-38m15 38 9-26m12 26-2-32m15 32 7-25m12 25 8-39m14 39 9-26"></path>
  </svg>`;
  intro.append(motif);
  return true;
}

function observePageIntro() {
  if (decoratePageIntro() || !document.querySelector('[data-detail]')) return;
  const root = document.querySelector('main') || document.body;
  const observer = new MutationObserver(() => {
    if (decoratePageIntro()) observer.disconnect();
  });
  observer.observe(root, { childList: true, subtree: true });
}

export async function refreshUnreadCount() {
  const badge = document.querySelector('[data-unread-badge]');
  if (!badge) return;
  try {
    const items = await api.notifications(true);
    badge.textContent = items.length > 99 ? '99+' : String(items.length);
    badge.hidden = items.length === 0;
    badge.setAttribute('aria-label', `${items.length} unread notifications`);
  } catch {
    badge.hidden = true;
  }
}

renderNavigation();
