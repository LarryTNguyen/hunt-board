import '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { activateCompanyLogos, companyMark, country, escapeHtml as esc, label, relativeDate, safeUrl, salary, score } from '../format.js?v=20260721-2';
import { debounce, loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const PAGE_SIZE = 9;
const validSorts = new Set(['recent', 'score', 'oldest']);
const board = document.querySelector('[data-board]');
const form = document.querySelector('[data-filter-form]');
const search = document.querySelector('[data-search]');
const company = document.querySelector('[data-company]');
const locationFilter = document.querySelector('[data-location]');
const sort = document.querySelector('[data-sort]');
const count = document.querySelector('[data-count]');
const pagination = document.querySelector('[data-pagination]');
const pageSummary = document.querySelector('[data-page-summary]');
const previousButton = document.querySelector('[data-previous]');
const nextButton = document.querySelector('[data-next]');
let savedJobs = [];
let hasNextPage = false;
let loadVersion = 0;
let state = readState();

function readState() {
  const params = new URLSearchParams(window.location.search);
  const requestedPage = Number.parseInt(params.get('page') || '1', 10);
  const requestedSort = params.get('sort') || 'recent';
  return {
    q: (params.get('q') || '').trim(),
    company: (params.get('company') || '').trim(),
    location: (params.get('location') || '').trim(),
    sort: validSorts.has(requestedSort) ? requestedSort : 'recent',
    page: Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
  };
}

function syncControls() {
  search.value = state.q;
  company.value = state.company;
  locationFilter.value = state.location;
  sort.value = state.sort;
}

function updateUrl(updates, { replace = false } = {}) {
  state = { ...state, ...updates };
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.company) params.set('company', state.company);
  if (state.location) params.set('location', state.location);
  if (state.sort !== 'recent') params.set('sort', state.sort);
  if (state.page > 1) params.set('page', String(state.page));
  const url = `${window.location.pathname}${params.size ? `?${params}` : ''}`;
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
  syncControls();
}

function hasFilters() {
  return Boolean(state.q || state.company || state.location);
}

function render() {
  count.textContent = `Page ${state.page} · ${savedJobs.length} saved job${savedJobs.length === 1 ? '' : 's'}`;
  pageSummary.textContent = `Page ${state.page}`;
  previousButton.disabled = state.page === 1;
  nextButton.disabled = !hasNextPage;
  pagination.hidden = state.page === 1 && !hasNextPage;
  if (!savedJobs.length) {
    const link = Object.assign(document.createElement('a'), { className: 'button button-primary', href: '/app/job-discovery.html', textContent: 'Find jobs to save' });
    renderEmpty(board, hasFilters() ? 'No pinned cards match' : 'Your field board is ready', hasFilters() ? 'Try different keywords, company, or location filters.' : 'Save a sighting to pin its card and notes here.', link);
    return;
  }
  const grid = document.createElement('div');
  grid.className = 'wanted-grid';
  savedJobs.forEach((item) => {
    const card = document.createElement('article');
    const official = safeUrl(item.job.apply_url);
    card.className = 'wanted-card';
    card.innerHTML = `<div class="wanted-kicker">Wanted / ${score(item.job.ranking_score)} match</div><div class="company-lockup">${companyMark(item.job.company_name, item.job.company_logo_url)}<span><h2>${esc(item.job.title)}</h2><p class="wanted-company">${esc(item.job.company_name)}</p></span></div><div class="wanted-meta"><div><small>Family</small>${esc(label(item.job.job_family_slug, 'Other'))}</div><div><small>Location</small>${esc(item.job.location || 'Not listed')}</div><div><small>Country</small>${esc(country(item.job))}</div><div><small>Compensation</small>${esc(salary(item.job))}</div><div><small>Source</small>${esc(label(item.job.source_slug))}</div><div><small>Saved</small>${esc(relativeDate(item.saved_at))}</div><div><small>Application</small>${esc(item.application_status?.name || 'Not started')}</div></div><label class="field-label" for="note-${item.id}">Field note</label><textarea class="wanted-note wanted-note-input" id="note-${item.id}" rows="4">${esc(item.notes || '')}</textarea><p class="form-status" data-status aria-live="polite"></p><div class="action-row"><button class="button" type="button" data-note>Save note</button>${official ? `<a class="button button-primary" href="${esc(official)}" target="_blank" rel="noopener noreferrer">Open official posting</a>` : ''}<button class="button button-primary" type="button" data-track>${item.application_status ? 'Move to tracker' : 'Add to tracker'}</button><a class="button button-dark" href="/app/job-detail.html?id=${item.job.id}">Open dossier</a><button class="button button-danger" type="button" data-remove>Remove</button></div>`;
    activateCompanyLogos(card);
    card.querySelector('[data-note]').addEventListener('click', (event) => saveNote(item, card, event.currentTarget));
    card.querySelector('[data-track]').addEventListener('click', (event) => addToTracker(item, card, event.currentTarget));
    card.querySelector('[data-remove]').addEventListener('click', (event) => remove(item, event.currentTarget));
    grid.append(card);
  });
  board.replaceChildren(grid);
}

async function addToTracker(item, card, button) {
  setBusy(button, true);
  const status = card.querySelector('[data-status]');
  const notes = card.querySelector('textarea').value.trim();
  let applicationAdded = false;
  status.textContent = 'Adding to the application tracker…';
  try {
    await api.createApplication(item.job.id, notes ? { notes } : {});
    applicationAdded = true;
    status.textContent = 'Added to the tracker. Removing the saved card…';
    await api.unsaveJob(item.job.id);
    makeToast('Job added to the tracker and removed from saved jobs.');
    await load();
  } catch (error) {
    const message = applicationAdded
      ? 'The job is in the tracker, but its saved card could not be removed. Try this action again.'
      : error.message;
    status.textContent = message;
    makeToast(message, 'error');
    setBusy(button, false);
  }
}

async function saveNote(item, card, button) {
  setBusy(button, true);
  const status = card.querySelector('[data-status]');
  status.textContent = 'Saving note…';
  try {
    const updated = await api.updateSaved(item.id, card.querySelector('textarea').value);
    item.notes = updated.notes;
    status.textContent = 'Note saved.';
    makeToast('Saved-job note updated.');
  } catch (error) {
    status.textContent = error.message;
    makeToast(error.message, 'error');
  }
  setBusy(button, false);
}

async function remove(item, button) {
  setBusy(button, true);
  try {
    await api.unsaveJob(item.job.id);
    makeToast('Job removed from the field board.');
    await load();
  } catch (error) {
    makeToast(error.message, 'error');
    setBusy(button, false);
  }
}

async function load() {
  const version = ++loadVersion;
  loading(board, 'Pinning the saved field board…', 'cards');
  previousButton.disabled = true;
  nextButton.disabled = true;
  try {
    const items = await api.savedJobs({
      limit: PAGE_SIZE + 1,
      offset: (state.page - 1) * PAGE_SIZE,
      q: state.q,
      company: state.company,
      location: state.location,
      sort: state.sort,
    });
    if (version !== loadVersion) return;
    if (!items.length && state.page > 1) {
      updateUrl({ page: state.page - 1 }, { replace: true });
      await load();
      return;
    }
    hasNextPage = items.length > PAGE_SIZE;
    savedJobs = items.slice(0, PAGE_SIZE);
    render();
  } catch (error) {
    if (version !== loadVersion) return;
    count.textContent = 'Saved jobs unavailable';
    pagination.hidden = true;
    renderError(board, error, load);
  }
}

const applyFilters = debounce(() => {
  updateUrl({ q: search.value.trim(), company: company.value.trim(), location: locationFilter.value.trim(), page: 1 });
  load();
}, 220);

search.addEventListener('input', applyFilters);
company.addEventListener('input', applyFilters);
locationFilter.addEventListener('input', applyFilters);
sort.addEventListener('change', () => { updateUrl({ sort: sort.value, page: 1 }); load(); });
form.addEventListener('submit', (event) => event.preventDefault());
form.querySelector('[data-clear]').addEventListener('click', () => { updateUrl({ q: '', company: '', location: '', page: 1 }); load(); });
previousButton.addEventListener('click', () => { if (state.page > 1) { updateUrl({ page: state.page - 1 }); load(); } });
nextButton.addEventListener('click', () => { if (hasNextPage) { updateUrl({ page: state.page + 1 }); load(); } });
window.addEventListener('popstate', () => { state = readState(); syncControls(); load(); });

syncControls();
load();
