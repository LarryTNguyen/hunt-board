import { refreshUnreadCount } from '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { escapeHtml as esc, label, relativeDate, truncate } from '../format.js?v=20260721-1';
import { loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const list = document.querySelector('[data-list]');
const tabs = document.querySelector('[data-tabs]');
let notifications = [];
let activeKind = 'all';

function notificationCopy(item) {
  const payload = item.payload_json || {};
  const titles = {
    new_match: 'New route match', reposted_job: 'A saved trail appeared again', job_updated: 'A watched posting changed',
  };
  const title = payload.title || payload.job_title || payload.subject || titles[item.kind] || label(item.kind, 'Hunt Board signal');
  const company = payload.company_name || payload.company;
  const detail = payload.message || payload.body || payload.summary || payload.reason || payload.description;
  const fallback = item.kind === 'new_match' ? 'A listing reached your matching threshold.' : item.kind === 'reposted_job' ? 'An inactive listing returned to an observed source.' : item.kind === 'job_updated' ? 'A saved or tracked job has new source content.' : 'Hunt Board recorded a new signal for this workspace.';
  return { title: company && !String(title).includes(company) ? `${title} at ${company}` : title, body: truncate(detail || fallback, 360) };
}

function renderTabs() {
  const kinds = [...new Set(notifications.map((item) => item.kind))].sort();
  tabs.replaceChildren();
  [['all', 'All dispatches'], ...kinds.map((kind) => [kind, label(kind)])].forEach(([kind, name]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.kind = kind;
    button.setAttribute('aria-pressed', String(kind === activeKind));
    const total = kind === 'all' ? notifications.length : notifications.filter((item) => item.kind === kind).length;
    button.innerHTML = `<span>${esc(name)}</span><span>${total}</span>`;
    button.addEventListener('click', () => { activeKind = kind; renderTabs(); renderList(); });
    tabs.append(button);
  });
}

function renderList() {
  const items = activeKind === 'all' ? notifications : notifications.filter((item) => item.kind === activeKind);
  if (!items.length) { renderEmpty(list, notifications.length ? 'No dispatches of this kind' : 'The signal desk is quiet', notifications.length ? 'Choose another dispatch filter.' : 'New matches, reposts, and updates will appear here.'); return; }
  list.innerHTML = items.map((item) => {
    const copy = notificationCopy(item);
    return `<article class="dispatch-item ${item.read_at ? '' : 'is-unread'}" data-id="${item.id}"><span class="dispatch-dot" aria-hidden="true"></span><div><p class="utility-label">${esc(label(item.kind))}${item.read_at ? ' / Read' : ' / Unread'}</p><h2>${esc(copy.title)}</h2><p>${esc(copy.body)}</p><div class="dispatch-actions">${item.job_posting_id ? `<a class="text-button" data-open-sighting href="/app/job-detail.html?v=20260721-1&id=${item.job_posting_id}">Open sighting</a>` : ''}${item.read_at ? '' : '<button class="text-button" type="button" data-read>Mark read</button>'}</div></div><time class="dispatch-time" datetime="${esc(item.created_at)}">${esc(relativeDate(item.created_at))}</time></article>`;
  }).join('');
  list.querySelectorAll('[data-read]').forEach((button) => button.addEventListener('click', () => markRead(button.closest('[data-id]'), button)));
  list.querySelectorAll('[data-open-sighting]').forEach((link) => {
    const row = link.closest('[data-id]');
    const item = notifications.find((entry) => entry.id === Number(row.dataset.id));
    link.addEventListener('click', (event) => openSighting(event, item, link));
  });
}

async function openSighting(event, item, link) {
  if (item.read_at || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  if (link.getAttribute('aria-busy') === 'true') return;

  const href = link.href;
  link.setAttribute('aria-busy', 'true');
  link.setAttribute('aria-disabled', 'true');
  try {
    const updated = await api.readNotification(item.id);
    const index = notifications.findIndex((entry) => entry.id === updated.id);
    if (index !== -1) notifications[index] = updated;
    renderList();
    await refreshUnreadCount();
    window.location.assign(href);
  } catch (error) {
    link.removeAttribute('aria-busy');
    link.removeAttribute('aria-disabled');
    makeToast(error.message, 'error');
  }
}

async function markRead(row, button) {
  setBusy(button, true);
  try {
    const updated = await api.readNotification(row.dataset.id);
    const index = notifications.findIndex((item) => item.id === updated.id);
    notifications[index] = updated;
    renderList();
    await refreshUnreadCount();
    makeToast('Dispatch marked as read.');
  } catch (error) { makeToast(error.message, 'error'); setBusy(button, false); }
}

async function markAll(button) {
  setBusy(button, true);
  try {
    const result = await api.readAllNotifications();
    const now = new Date().toISOString();
    notifications.forEach((item) => { if (!item.read_at) item.read_at = now; });
    renderList();
    await refreshUnreadCount();
    makeToast(`${result.marked_read} dispatch${result.marked_read === 1 ? '' : 'es'} marked read.`);
  } catch (error) { makeToast(error.message, 'error'); }
  setBusy(button, false);
}

async function load() {
  loading(list, 'Tuning the incoming signal desk…');
  try { notifications = await api.notifications(); renderTabs(); renderList(); } catch (error) { renderError(list, error, load); }
}

document.querySelector('[data-read-all]').addEventListener('click', (event) => markAll(event.currentTarget));
load();
