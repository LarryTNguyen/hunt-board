import '../navigation.js?v=20260722-4';
import { api } from '../api.js?v=20260722-4';
import { absoluteDate, activateCompanyLogos, companyMark, country, escapeHtml as esc, label, plainText, rankingSignals, relativeDate, roleLevel, safeUrl, salary, score, truncate } from '../format.js?v=20260721-2';
import { debounce, loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const LIMIT = 25;
const tabs = new Set(['all', 'new', 'saved', 'top', 'discarded']);
const sorts = new Set(['ranking_score:desc', 'relevance:desc', 'posted_at:desc', 'first_seen_at:desc', 'company_name:asc', 'title:asc']);
const postedValues = new Set(['1', '3', '7', '14', '30', '90']);
const salaryValues = new Set(['known', 'unknown']);
const scoreValues = new Set(['60', '70', '80', '90']);

const results = document.querySelector('[data-results]');
const drawer = document.querySelector('[data-drawer]');
const count = document.querySelector('[data-count]');
const freshness = document.querySelector('[data-freshness]');
const pagination = document.querySelector('[data-pagination]');
const pageSummary = document.querySelector('[data-page-summary]');
const previousButton = document.querySelector('[data-previous]');
const nextButton = document.querySelector('[data-next]');
const controls = {
  q: document.querySelector('[data-search]'),
  source: document.querySelector('[data-source]'),
  ats: document.querySelector('[data-ats]'),
  country: document.querySelector('[data-country]'),
  location: document.querySelector('[data-location]'),
  workplace: document.querySelector('[data-workplace]'),
  salary: document.querySelector('[data-salary]'),
  posted: document.querySelector('[data-posted]'),
  score: document.querySelector('[data-score]'),
  sort: document.querySelector('[data-sort]'),
};

let jobs = [];
let feed = null;
let topThreshold = 90;
let currentState = readState();
let loadSequence = 0;

function positiveInteger(value) {
  const parsed = Number.parseInt(value || '', 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function nonnegativeInteger(value) {
  const parsed = Number.parseInt(value || '', 10);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function readState() {
  const params = new URLSearchParams(window.location.search);
  const q = (params.get('q') || '').trim();
  const requestedSort = params.get('sort');
  return {
    q,
    source: (params.get('source') || '').trim(),
    ats: (params.get('ats') || '').trim().toLowerCase(),
    country: (params.get('country') || '').trim(),
    location: (params.get('location') || '').trim(),
    workplace: (params.get('workplace') || '').trim(),
    salary: salaryValues.has(params.get('salary')) ? params.get('salary') : '',
    posted: postedValues.has(params.get('posted')) ? params.get('posted') : '',
    score: scoreValues.has(params.get('score')) ? params.get('score') : '',
    sort: sorts.has(requestedSort) ? requestedSort : (q ? 'relevance:desc' : 'ranking_score:desc'),
    offset: nonnegativeInteger(params.get('offset')),
    job: positiveInteger(params.get('job')),
    tab: tabs.has(params.get('tab')) ? params.get('tab') : 'all',
  };
}

function locationSummary(job) {
  const locations = Array.isArray(job.locations) ? job.locations.filter((item) => item?.display) : [];
  if (!locations.length) return job.location || 'Location not listed';
  return locations.length === 1 ? locations[0].display : `${locations[0].display} + ${locations.length - 1} more`;
}

function allLocations(job) {
  const locations = Array.isArray(job.locations) ? job.locations.filter((item) => item?.display) : [];
  return locations.length ? locations.map((item) => item.display).join(' / ') : (job.location || 'Not listed');
}

function feedSignature(state) {
  return JSON.stringify({ ...state, job: null });
}

function updateUrl(updates, { replace = false, resetOffset = true, load = true } = {}) {
  const params = new URLSearchParams(window.location.search);
  Object.entries(updates).forEach(([key, value]) => {
    if (value === '' || value === null || value === undefined || value === false) params.delete(key);
    else params.set(key, String(value));
  });
  if (resetOffset && !Object.prototype.hasOwnProperty.call(updates, 'offset')) params.delete('offset');
  const url = `${window.location.pathname}${params.size ? `?${params}` : ''}`;
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
  currentState = readState();
  syncControls();
  if (load) loadFeed();
}

function syncControls() {
  Object.entries(controls).forEach(([key, control]) => { control.value = currentState[key] || ''; });
  document.querySelectorAll('[data-tab]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.tab === currentState.tab));
  });
}

function feedParams() {
  const [sortBy, sortOrder] = currentState.sort.split(':');
  const params = {
    q: currentState.q,
    active: true,
    source_slug: currentState.source,
    ats: currentState.ats,
    country: currentState.country,
    location: currentState.location,
    workplace_type: currentState.workplace,
    salary_known: currentState.salary === 'known' ? true : currentState.salary === 'unknown' ? false : undefined,
    posted_within_days: currentState.posted,
    min_score: currentState.score,
    sort_by: sortBy,
    sort_order: sortOrder,
    limit: LIMIT,
    offset: currentState.offset,
    application_state: 'none',
    discarded: false,
    include_duplicates: false,
  };
  if (currentState.tab === 'new') params.saved = false;
  if (currentState.tab === 'saved') params.saved = true;
  if (currentState.tab === 'top') params.min_score = Math.max(topThreshold, Number(currentState.score || 0));
  if (currentState.tab === 'discarded') {
    params.active = undefined;
    params.discarded = true;
    params.application_state = 'any';
  }
  return params;
}

function stateLabel(job) {
  if (job.has_application) return job.application_status?.name || 'Tracked';
  if (job.is_saved) return 'Saved';
  if (job.is_reposted) return 'Reposted';
  return 'New';
}

function renderRows() {
  results.setAttribute('aria-busy', 'false');
  if (!jobs.length) {
    const action = Object.assign(document.createElement('button'), { className: 'button', type: 'button', textContent: 'Clear filters' });
    action.addEventListener('click', clearAll);
    renderEmpty(results, currentState.tab === 'discarded' ? 'The discard pile is clear' : 'No sightings match this route', currentState.tab === 'discarded' ? 'Hidden jobs will wait here until you restore them.' : 'Try a broader search or clear one of the route filters.', action);
    count.textContent = feed?.total ? `0 of ${feed.total} sightings on this page` : '0 sightings';
    return;
  }
  const table = document.createElement('table');
  table.className = 'ledger';
  table.innerHTML = '<thead><tr><th>Status</th><th>Role</th><th>Company</th><th>Location</th><th>Country</th><th>Compensation</th><th>Source</th><th>Match</th><th>Seen</th></tr></thead><tbody></tbody>';
  const body = table.querySelector('tbody');
  jobs.forEach((job) => {
    const row = document.createElement('tr');
    row.tabIndex = 0;
    row.classList.toggle('is-selected', currentState.job === job.id);
    row.setAttribute('aria-label', `Open ${job.title} at ${job.company_name}`);
    row.innerHTML = `<td><span class="status ${job.is_saved ? '' : 'status-new'}">${esc(currentState.tab === 'discarded' ? 'Hidden' : stateLabel(job))}</span></td>
      <td><span class="ledger-title">${esc(job.title)}</span><span class="ledger-submeta">${esc(job.department || job.employment_type || 'General')}</span></td>
      <td><span class="company-lockup company-lockup-compact">${companyMark(job.company_name, job.company_logo_url)}<span>${esc(job.company_name)}</span></span></td><td>${esc(locationSummary(job))}</td>
      <td>${esc(country(job))}</td><td class="salary-cell">${esc(salary(job))}</td>
      <td><span class="source-tag">${esc(job.source?.ats || job.source_slug)}</span></td><td><span class="match-score">${score(job.ranking_score)}</span></td><td>${esc(relativeDate(job.first_seen_at))}</td>`;
    const open = () => openDrawer(job);
    row.addEventListener('click', open);
    row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
    body.append(row);
  });
  results.replaceChildren(table);
  activateCompanyLogos(results);
  const first = feed.offset + 1;
  const last = feed.offset + jobs.length;
  count.textContent = `Showing ${first}–${last} of ${feed.total} sighting${feed.total === 1 ? '' : 's'}`;
}

function renderPagination() {
  pagination.hidden = !feed || feed.total <= feed.limit;
  if (!feed) return;
  const page = Math.floor(feed.offset / feed.limit) + 1;
  const pages = Math.max(1, Math.ceil(feed.total / feed.limit));
  pageSummary.textContent = `Page ${page} of ${pages}`;
  previousButton.disabled = feed.offset === 0;
  nextButton.disabled = !feed.has_more;
}

function populateSelect(control, items, placeholder, selected) {
  control.replaceChildren(new Option(placeholder, ''));
  items.forEach((item) => control.append(new Option(`${item.label} (${item.count})`, item.value)));
  if (selected && !items.some((item) => item.value === selected)) control.append(new Option(selected, selected));
  control.value = selected || '';
}

function populateFacets(facets) {
  populateSelect(controls.source, facets.sources, 'All sources', currentState.source);
  populateSelect(controls.ats, facets.ats, 'All ATS platforms', currentState.ats);
  populateSelect(controls.country, facets.countries, 'All countries', currentState.country);
  populateSelect(controls.workplace, facets.workplace_types, 'Any arrangement', currentState.workplace);
}

async function openDrawer(job, updateHistory = true) {
  if (updateHistory && currentState.job !== job.id) updateUrl({ job: job.id }, { resetOffset: false, load: false });
  const official = safeUrl(job.apply_url) || safeUrl(job.posting_url);
  const relevance = rankingSignals(job);
  drawer.setAttribute('aria-hidden', 'false');
  drawer.classList.add('is-open');
  document.body.classList.add('drawer-open');
  drawer.innerHTML = `<div class="drawer-head"><span class="utility-label">Observation sheet / #${job.id}</span><button class="icon-button" type="button" data-close aria-label="Close observation sheet">×</button></div>
    <div class="drawer-body"><p class="utility-label">${esc(job.source?.ats || job.source_slug)} / ${esc(relativeDate(job.first_seen_at))}</p><h2>${esc(job.title)}</h2><div class="company-lockup drawer-company">${companyMark(job.company_name, job.company_logo_url)}<span>${esc(job.company_name)}</span></div>
    <div class="action-row">${job.is_saved ? '<span class="tag">Saved</span>' : ''}${job.has_application ? `<span class="tag">${esc(job.application_status?.name || 'Tracked')}</span>` : ''}${job.is_reposted ? '<span class="tag">Reposted</span>' : ''}</div>
    <div class="drawer-score"><span><small class="utility-label">Route relevance</small><strong>${score(job.ranking_score)}</strong></span><small>out of 100</small></div>
    <div class="relevance-summary">${relevance.map((signal) => `<div><small>${esc(signal.label)}</small><strong>${esc(signal.value)}</strong></div>`).join('')}</div>
    <dl class="meta-list"><div><dt>Locations</dt><dd>${esc(allLocations(job))}</dd></div><div><dt>Country</dt><dd>${esc(country(job))}</dd></div><div><dt>Compensation</dt><dd>${esc(salary(job))}</dd></div><div><dt>Role level</dt><dd>${esc(roleLevel(job.title))}</dd></div><div><dt>Work arrangement</dt><dd>${esc(label(job.workplace_type, 'Not provided by source'))}</dd></div><div><dt>First seen</dt><dd>${esc(absoluteDate(job.first_seen_at))}</dd></div><div><dt>Source</dt><dd>${esc(job.source?.name || job.source_slug)}</dd></div></dl>
    <section class="drawer-section"><h3>Field excerpt</h3><p>${esc(truncate(plainText(job.description_text) || 'No description text was supplied by the source.', 480))}</p></section>
    <div class="action-row drawer-actions">${currentState.tab === 'discarded' ? '<button class="button button-primary" type="button" data-restore>Restore to route</button>' : `${job.is_saved ? '<button class="button" type="button" data-unsave>Unsave</button>' : '<button class="button" type="button" data-save>Save</button>'}<button class="button" type="button" data-discard>Hide</button>${job.has_application ? '' : '<button class="button button-dark" type="button" data-track>Add to tracker</button>'}`}${official ? `<a class="button" href="${esc(official)}" target="_blank" rel="noopener noreferrer">Open official posting</a>` : ''}<a class="button button-primary" href="/app/job-detail.html?id=${job.id}">View full dossier</a></div></div>`;
  drawer.querySelector('[data-close]').addEventListener('click', () => closeDrawer());
  activateCompanyLogos(drawer);
  drawer.querySelector('[data-save]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.saveJob(job.id); makeToast('Job saved to the field board.'); await loadFeed(); }));
  drawer.querySelector('[data-unsave]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.unsaveJob(job.id); makeToast('Job removed from the field board.'); await loadFeed(); }));
  drawer.querySelector('[data-discard]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.discardJob(job.id); makeToast('Job moved to the discard pile.'); closeDrawer(); await loadFeed(); }));
  drawer.querySelector('[data-restore]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.restoreJob(job.id); makeToast('Job restored to the daily route.'); closeDrawer(); await loadFeed(); }));
  drawer.querySelector('[data-track]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.createApplication(job.id); makeToast('Application added to the tracker and removed from discovery.'); closeDrawer(); await loadFeed(); }));
  renderRows();
  drawer.querySelector('[data-close]').focus();
}

async function mutate(button, callback) {
  setBusy(button, true);
  try { await callback(); } catch (error) { makeToast(error.message, 'error'); setBusy(button, false); }
}

function closeDrawer(updateHistory = true) {
  drawer.classList.remove('is-open');
  drawer.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('drawer-open');
  drawer.replaceChildren();
  if (updateHistory && currentState.job) updateUrl({ job: null }, { resetOffset: false, load: false });
  if (jobs.length) renderRows();
}

async function restoreDrawer() {
  if (!currentState.job) {
    closeDrawer(false);
    return;
  }
  const localJob = jobs.find((job) => job.id === currentState.job);
  try {
    await openDrawer(localJob || await api.job(currentState.job), false);
  } catch (error) {
    makeToast(`Selected job could not be opened: ${error.message}`, 'error');
    updateUrl({ job: null }, { replace: true, resetOffset: false, load: false });
    closeDrawer(false);
  }
}

async function loadFeed() {
  const sequence = ++loadSequence;
  results.setAttribute('aria-busy', 'true');
  pagination.hidden = true;
  loading(results, currentState.tab === 'discarded' ? 'Opening the discard pile…' : 'Reading this route from the server…');
  try {
    const payload = await api.discoveryFeed(feedParams());
    if (sequence !== loadSequence) return;
    feed = payload;
    jobs = payload.items;
    populateFacets(payload.facets);
    renderRows();
    renderPagination();
    await restoreDrawer();
  } catch (error) {
    if (sequence !== loadSequence) return;
    results.setAttribute('aria-busy', 'false');
    renderError(results, error, loadFeed);
    count.textContent = 'Sightings unavailable';
  }
}

async function loadFreshness() {
  try {
    const health = await api.ingestionHealth();
    if (health.status === 'ok') {
      freshness.textContent = health.last_successful_at ? `Last successful refresh ${relativeDate(health.last_successful_at)}` : 'No successful refresh has been recorded yet';
      freshness.dataset.state = 'ok';
    } else {
      const attention = health.unhealthy_sources + health.stale_running_runs;
      freshness.textContent = `${attention || health.due_sources} source${attention === 1 ? '' : 's'} need attention; listings may be incomplete`;
      freshness.dataset.state = 'degraded';
    }
  } catch {
    freshness.textContent = 'Refresh status unavailable; job browsing is still available';
    freshness.dataset.state = 'unknown';
  }
}

function clearAll() {
  window.history.pushState({}, '', window.location.pathname);
  currentState = readState();
  syncControls();
  closeDrawer(false);
  loadFeed();
}

document.querySelector('[data-filter-form]').addEventListener('submit', (event) => event.preventDefault());
document.querySelector('[data-clear]').addEventListener('click', clearAll);
document.querySelector('[data-tabs]').addEventListener('click', (event) => {
  const button = event.target.closest('[data-tab]');
  if (button) updateUrl({ tab: button.dataset.tab === 'all' ? null : button.dataset.tab });
});

const updateSearch = debounce(() => updateUrl({ q: controls.q.value.trim() }, { replace: true }), 350);
const updateLocation = debounce(() => updateUrl({ location: controls.location.value.trim() }, { replace: true }), 350);
controls.q.addEventListener('input', updateSearch);
controls.location.addEventListener('input', updateLocation);
['source', 'ats', 'country', 'workplace', 'salary', 'posted', 'score', 'sort'].forEach((key) => {
  controls[key].addEventListener('change', () => updateUrl({ [key]: controls[key].value }));
});
previousButton.addEventListener('click', () => updateUrl({ offset: Math.max(0, currentState.offset - LIMIT) }, { resetOffset: false }));
nextButton.addEventListener('click', () => updateUrl({ offset: currentState.offset + LIMIT }, { resetOffset: false }));
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && currentState.job) closeDrawer(); });
window.addEventListener('popstate', () => {
  const previousSignature = feedSignature(currentState);
  currentState = readState();
  syncControls();
  if (previousSignature === feedSignature(currentState)) restoreDrawer();
  else loadFeed();
});

syncControls();
try {
  const preferences = await api.preferences();
  topThreshold = Math.max(90, Number(preferences.minimum_score_threshold || 0));
} catch {
  topThreshold = 90;
}
loadFreshness();
loadFeed();
