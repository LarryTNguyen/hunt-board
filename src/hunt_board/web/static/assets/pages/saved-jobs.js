import '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { activateCompanyLogos, companyMark, country, escapeHtml as esc, label, relativeDate, salary, score } from '../format.js?v=20260721-2';
import { debounce, loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const board = document.querySelector('[data-board]');
const search = document.querySelector('[data-search]');
const sort = document.querySelector('[data-sort]');
const count = document.querySelector('[data-count]');
let savedJobs = [];

function visibleItems() {
  const term = search.value.trim().toLowerCase();
  const items = savedJobs.filter((item) => `${item.job.title} ${item.job.company_name} ${item.job.location || ''} ${item.job.source_slug}`.toLowerCase().includes(term));
  return items.sort((a, b) => sort.value === 'score' ? b.job.ranking_score - a.job.ranking_score : sort.value === 'oldest' ? new Date(a.saved_at) - new Date(b.saved_at) : new Date(b.saved_at) - new Date(a.saved_at));
}

function render() {
  const items = visibleItems();
  count.textContent = `${items.length} saved job${items.length === 1 ? '' : 's'}`;
  if (!items.length) {
    const link = Object.assign(document.createElement('a'), { className: 'button button-primary', href: '/app/job-discovery.html', textContent: 'Find jobs to save' });
    renderEmpty(board, savedJobs.length ? 'No pinned cards match' : 'Your field board is ready', savedJobs.length ? 'Try a different title, company, location, or source.' : 'Save a sighting to pin its card and notes here.', link);
    return;
  }
  const grid = document.createElement('div');
  grid.className = 'wanted-grid';
  items.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'wanted-card';
    card.innerHTML = `<div class="wanted-kicker">Wanted / ${score(item.job.ranking_score)} match</div><div class="company-lockup">${companyMark(item.job.company_name, item.job.company_logo_url)}<span><h2>${esc(item.job.title)}</h2><p class="wanted-company">${esc(item.job.company_name)}</p></span></div><div class="wanted-meta"><div><small>Location</small>${esc(item.job.location || 'Not listed')}</div><div><small>Country</small>${esc(country(item.job))}</div><div><small>Compensation</small>${esc(salary(item.job))}</div><div><small>Source</small>${esc(label(item.job.source_slug))}</div><div><small>Saved</small>${esc(relativeDate(item.saved_at))}</div><div><small>Application</small>${esc(item.application_status?.name || 'Not started')}</div></div><label class="field-label" for="note-${item.id}">Field note</label><textarea class="wanted-note wanted-note-input" id="note-${item.id}" rows="4">${esc(item.notes || '')}</textarea><p class="form-status" data-status aria-live="polite"></p><div class="action-row"><button class="button" type="button" data-note>Save note</button><a class="button button-dark" href="/app/job-detail.html?id=${item.job.id}">Open dossier</a><button class="button button-danger" type="button" data-remove>Remove</button></div>`;
    activateCompanyLogos(card);
    card.querySelector('[data-note]').addEventListener('click', (event) => saveNote(item, card, event.currentTarget));
    card.querySelector('[data-remove]').addEventListener('click', (event) => remove(item, event.currentTarget));
    grid.append(card);
  });
  board.replaceChildren(grid);
}

async function saveNote(item, card, button) {
  setBusy(button, true);
  const status = card.querySelector('[data-status]');
  status.textContent = 'Saving note…';
  try { const updated = await api.updateSaved(item.id, card.querySelector('textarea').value); item.notes = updated.notes; status.textContent = 'Note saved.'; makeToast('Saved-job note updated.'); } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); }
  setBusy(button, false);
}

async function remove(item, button) {
  setBusy(button, true);
  try { await api.unsaveJob(item.job.id); savedJobs = savedJobs.filter((entry) => entry.id !== item.id); render(); makeToast('Job removed from the field board.'); } catch (error) { makeToast(error.message, 'error'); setBusy(button, false); }
}

async function load() {
  loading(board, 'Unpinning the saved field board…');
  try { savedJobs = await api.savedJobs(); render(); } catch (error) { renderError(board, error, load); }
}
search.addEventListener('input', debounce(render, 180));
sort.addEventListener('change', render);
load();
