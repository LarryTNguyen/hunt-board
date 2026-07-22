import '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { absoluteDate, activateCompanyLogos, companyMark, country, escapeHtml as esc, label, plainText, rankingSignals, relativeDate, roleLevel, safeUrl, salary, score, truncate } from '../format.js?v=20260721-2';
import { debounce, loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const results = document.querySelector('[data-results]');
const drawer = document.querySelector('[data-drawer]');
const count = document.querySelector('[data-count]');
const search = document.querySelector('[data-search]');
const locationSelect = document.querySelector('[data-location]');
const countrySelect = document.querySelector('[data-country]');
const sortSelect = document.querySelector('[data-sort]');
let activeTab = 'all';
let jobs = [];
let minimumThreshold = 0;
let topThreshold = 90;
let selectedId = null;

function stateLabel(job) {
  if (job.has_application) return job.application_status?.name || 'Tracked';
  if (job.is_saved) return 'Saved';
  if (job.is_reposted) return 'Reposted';
  return 'New';
}

function renderRows() {
  if (!jobs.length) {
    const action = activeTab === 'discarded' ? null : Object.assign(document.createElement('button'), { className: 'button', textContent: 'Clear search' });
    if (action) action.addEventListener('click', () => { search.value = ''; load(); });
    renderEmpty(results, activeTab === 'discarded' ? 'The discard pile is clear' : 'No sightings match this route', activeTab === 'discarded' ? 'Hidden jobs will wait here until you restore them.' : 'Try a broader search or another filter.', action);
    count.textContent = '0 sightings';
    return;
  }
  const table = document.createElement('table');
  table.className = 'ledger';
  table.innerHTML = '<thead><tr><th>Status</th><th>Role</th><th>Company</th><th>Location</th><th>Country</th><th>Compensation</th><th>Source</th><th>Match</th><th>Seen</th></tr></thead><tbody></tbody>';
  const body = table.querySelector('tbody');
  jobs.forEach((job) => {
    const row = document.createElement('tr');
    row.tabIndex = 0;
    row.setAttribute('aria-label', `Open ${job.title} at ${job.company_name}`);
    row.innerHTML = `<td><span class="status ${job.is_saved ? '' : 'status-new'}">${esc(activeTab === 'discarded' ? 'Hidden' : stateLabel(job))}</span></td>
      <td><span class="ledger-title">${esc(job.title)}</span><span class="ledger-submeta">${esc(job.department || job.employment_type || 'General')}</span></td>
      <td><span class="company-lockup company-lockup-compact">${companyMark(job.company_name, job.company_logo_url)}<span>${esc(job.company_name)}</span></span></td><td>${esc(job.location || 'Location not listed')}</td>
      <td>${esc(country(job))}</td><td class="salary-cell">${esc(salary(job))}</td>
      <td><span class="source-tag">${esc(job.source?.ats || job.source_slug)}</span></td><td><span class="match-score">${score(job.ranking_score)}</span></td><td>${esc(relativeDate(job.first_seen_at))}</td>`;
    const open = () => openDrawer(job);
    row.addEventListener('click', open);
    row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
    body.append(row);
  });
  results.replaceChildren(table);
  activateCompanyLogos(results);
  count.textContent = `${jobs.length} sighting${jobs.length === 1 ? '' : 's'}`;
}

async function openDrawer(job) {
  const official = safeUrl(job.apply_url) || safeUrl(job.posting_url);
  const relevance = rankingSignals(job);
  selectedId = job.id;
  drawer.setAttribute('aria-hidden', 'false');
  drawer.classList.add('is-open');
  document.body.classList.add('drawer-open');
  drawer.innerHTML = `<div class="drawer-head"><span class="utility-label">Observation sheet / #${job.id}</span><button class="icon-button" type="button" data-close aria-label="Close observation sheet">×</button></div>
    <div class="drawer-body"><p class="utility-label">${esc(job.source?.ats || job.source_slug)} / ${esc(relativeDate(job.first_seen_at))}</p><h2>${esc(job.title)}</h2><div class="company-lockup drawer-company">${companyMark(job.company_name, job.company_logo_url)}<span>${esc(job.company_name)}</span></div>
    <div class="action-row">${job.is_saved ? '<span class="tag">Saved</span>' : ''}${job.has_application ? `<span class="tag">${esc(job.application_status?.name || 'Tracked')}</span>` : ''}${job.is_reposted ? '<span class="tag">Reposted</span>' : ''}</div>
    <div class="drawer-score"><span><small class="utility-label">Route relevance</small><strong>${score(job.ranking_score)}</strong></span><small>out of 100</small></div>
    <div class="relevance-summary">${relevance.map((signal) => `<div><small>${esc(signal.label)}</small><strong>${esc(signal.value)}</strong></div>`).join('')}</div>
    <dl class="meta-list"><div><dt>Location</dt><dd>${esc(job.location || 'Not listed')}</dd></div><div><dt>Country</dt><dd>${esc(country(job))}</dd></div><div><dt>Compensation</dt><dd>${esc(salary(job))}</dd></div><div><dt>Role level</dt><dd>${esc(roleLevel(job.title))}</dd></div><div><dt>Work arrangement</dt><dd>${esc(label(job.workplace_type, 'Not provided by source'))}</dd></div><div><dt>First seen</dt><dd>${esc(absoluteDate(job.first_seen_at))}</dd></div><div><dt>Source</dt><dd>${esc(job.source?.name || job.source_slug)}</dd></div></dl>
    <section class="drawer-section"><h3>Field excerpt</h3><p>${esc(truncate(plainText(job.description_text) || 'No description text was supplied by the source.', 480))}</p></section>
    <div class="action-row drawer-actions">${activeTab === 'discarded' ? '<button class="button button-primary" type="button" data-restore>Restore to route</button>' : `${job.is_saved ? '<button class="button" type="button" data-unsave>Unsave</button>' : '<button class="button" type="button" data-save>Save</button>'}<button class="button" type="button" data-discard>Hide</button>${job.has_application ? '' : '<button class="button button-dark" type="button" data-track>Add to tracker</button>'}`}${official ? `<a class="button" href="${esc(official)}" target="_blank" rel="noopener noreferrer">Open official posting</a>` : ''}<a class="button button-primary" href="/app/job-detail.html?id=${job.id}">View full dossier</a></div></div>`;
  drawer.querySelector('[data-close]').addEventListener('click', closeDrawer);
  activateCompanyLogos(drawer);
  drawer.querySelector('[data-save]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { const saved = await api.saveJob(job.id); job.is_saved = true; job.saved_job_id = saved.id; makeToast('Job saved to the field board.'); openDrawer(job); renderRows(); }));
  drawer.querySelector('[data-unsave]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.unsaveJob(job.id); job.is_saved = false; job.saved_job_id = null; makeToast('Job removed from the field board.'); openDrawer(job); renderRows(); }));
  drawer.querySelector('[data-discard]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.discardJob(job.id); makeToast('Job moved to the discard pile.'); closeDrawer(); await load(); }));
  drawer.querySelector('[data-restore]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.restoreJob(job.id); makeToast('Job restored to the daily route.'); closeDrawer(); await load(); }));
  drawer.querySelector('[data-track]')?.addEventListener('click', (event) => mutate(event.currentTarget, async () => { await api.createApplication(job.id); jobs = jobs.filter((item) => item.id !== job.id); makeToast('Application added to the tracker and removed from discovery.'); closeDrawer(); renderRows(); }));
  drawer.querySelector('[data-close]').focus();
}

async function mutate(button, callback) {
  setBusy(button, true);
  try { await callback(); } catch (error) { makeToast(error.message, 'error'); setBusy(button, false); }
}

function closeDrawer() {
  drawer.classList.remove('is-open');
  drawer.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('drawer-open');
  drawer.replaceChildren();
  selectedId = null;
}

function populateLocations(items) {
  const existing = locationSelect.value;
  const values = [...new Set(items.map((job) => job.location).filter(Boolean))].sort();
  locationSelect.replaceChildren(new Option('All locations', ''), new Option('Remote only', 'remote'));
  values.forEach((value) => locationSelect.append(new Option(value, value)));
  locationSelect.value = existing;
}

function populateCountries(items) {
  const existing = countrySelect.value;
  const values = [...new Map(items.filter((job) => job.location_country_code).map((job) => [job.location_country_code, job.location_country || job.location_country_code])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  countrySelect.replaceChildren(new Option('All countries', ''));
  values.forEach(([code, name]) => countrySelect.append(new Option(name, code)));
  countrySelect.value = existing;
}

async function load() {
  closeDrawer();
  loading(results, activeTab === 'discarded' ? 'Opening the discard pile…' : 'Reading today’s sightings…');
  try {
    if (activeTab === 'discarded') {
      const discarded = await api.discardedJobs();
      jobs = discarded.map((entry) => ({ ...entry.job, is_discarded: true, source: { ats: entry.job.source_slug } }));
      if (search.value.trim()) {
        const term = search.value.trim().toLowerCase();
        jobs = jobs.filter((job) => `${job.title} ${job.company_name} ${job.location || ''}`.toLowerCase().includes(term));
      }
    } else {
      const [sortBy, sortOrder] = sortSelect.value.split(':');
      const params = { active: true, include_duplicates: false, discarded: false, min_score: minimumThreshold, limit: 200, sort_by: sortBy, sort_order: sortOrder, search: search.value.trim() };
      if (activeTab === 'saved') params.saved = true;
      if (activeTab === 'top') params.min_score = topThreshold;
      if (locationSelect.value === 'remote') params.remote_only = true;
      else if (locationSelect.value) params.location = locationSelect.value;
      if (countrySelect.value) params.country = countrySelect.value;
      jobs = await api.jobs(params);
      jobs = jobs.filter((job) => !job.has_application);
      if (activeTab === 'new') jobs = jobs.filter((job) => !job.is_saved && !job.has_application);
      populateLocations(jobs);
      populateCountries(jobs);
    }
    renderRows();
  } catch (error) { renderError(results, error, load); count.textContent = 'Sightings unavailable'; }
}

document.querySelector('[data-tabs]').addEventListener('click', (event) => {
  const button = event.target.closest('[data-tab]');
  if (!button) return;
  activeTab = button.dataset.tab;
  document.querySelectorAll('[data-tab]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
  locationSelect.disabled = activeTab === 'discarded';
  countrySelect.disabled = activeTab === 'discarded';
  sortSelect.disabled = activeTab === 'discarded';
  load();
});
search.addEventListener('input', debounce(load, 320));
locationSelect.addEventListener('change', load);
countrySelect.addEventListener('change', load);
sortSelect.addEventListener('change', load);
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && selectedId) closeDrawer(); });

try {
  minimumThreshold = Number((await api.preferences()).minimum_score_threshold || 0);
  topThreshold = Math.max(90, minimumThreshold);
} catch {
  minimumThreshold = 0;
  topThreshold = 90;
}
load();
