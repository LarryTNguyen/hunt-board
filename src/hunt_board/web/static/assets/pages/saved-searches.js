import '../navigation.js?v=20260727-5';
import { api } from '../api.js?v=20260727-5';
import { escapeHtml as esc, relativeDate, salary, score } from '../format.js?v=20260721-2';
import { makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const form = document.querySelector('[data-search-form]');
const listHost = document.querySelector('[data-search-list]');
const matchesSection = document.querySelector('[data-search-matches]');
const matchesHost = document.querySelector('[data-match-list]');
const matchTitle = document.querySelector('[data-match-title]');
const markReviewed = document.querySelector('[data-mark-reviewed]');
const newOnly = document.querySelector('[data-new-only]');
const cancelEdit = document.querySelector('[data-cancel-edit]');
const saveButton = document.querySelector('[data-save-search]');
const message = document.querySelector('[data-search-message]');

let searches = [];
let selectedId = Number(new URLSearchParams(window.location.search).get('search')) || null;

function describeFilters(filters) {
  const parts = [];
  if (filters.q) parts.push(`“${filters.q}”`);
  if (filters.country) parts.push(filters.country);
  if (filters.remote_only) parts.push('remote');
  if (filters.min_score != null) parts.push(`${filters.min_score}+ score`);
  if (filters.posted_within_days) parts.push(`${filters.posted_within_days} days`);
  return parts.join(' · ') || 'All eligible discovery jobs';
}

function discoveryUrl(search) {
  const filters = search.filters;
  const params = new URLSearchParams();
  const mappings = { q: 'q', source_slug: 'source', ats: 'ats', country: 'country', location: 'location', workplace_type: 'workplace', posted_within_days: 'posted', min_score: 'score' };
  Object.entries(mappings).forEach(([key, target]) => { if (filters[key] !== null && filters[key] !== undefined && filters[key] !== '') params.set(target, filters[key]); });
  if (filters.salary_known === true) params.set('salary', 'known');
  if (filters.salary_known === false) params.set('salary', 'unknown');
  params.set('sort', `${search.sort_by}:${search.sort_order}`);
  return `/app/job-discovery.html?${params}`;
}

function renderSearches() {
  if (!searches.length) {
    renderEmpty(listHost, 'No saved routes', 'Create one above or save the current route from discovery.');
    return;
  }
  listHost.innerHTML = searches.map((search) => `<article class="route-card ${search.is_default ? 'is-default' : ''} ${search.id === selectedId ? 'is-selected' : ''}" data-search-id="${search.id}">
    <div class="route-card-head"><span class="utility-label">${search.is_default ? 'Default route' : search.is_active ? 'Active route' : 'Paused route'}</span><span>${search.new_since_review_count} new</span></div>
    <h3>${esc(search.name)}</h3><p>${esc(search.description || describeFilters(search.filters))}</p>
    <dl><div><dt>Matches</dt><dd>${search.match_count}</dd></div><div><dt>Reviewed</dt><dd>${esc(search.last_viewed_at ? relativeDate(search.last_viewed_at) : 'Never')}</dd></div></dl>
    <div class="action-row"><button class="button button-primary" type="button" data-open>Open matches</button><button class="button" type="button" data-edit>Edit</button><a class="button button-quiet" href="${discoveryUrl(search)}">Discovery</a><button class="button button-quiet" type="button" data-delete>Delete</button></div>
  </article>`).join('');
}

function resetForm() {
  form.reset();
  form.elements.id.value = '';
  form.elements.is_active.checked = true;
  saveButton.textContent = 'Save route';
  cancelEdit.hidden = true;
  document.querySelector('#route-form-title').textContent = 'Create a saved route';
}

function editSearch(search) {
  const filters = search.filters;
  form.elements.id.value = search.id;
  form.elements.name.value = search.name;
  form.elements.description.value = search.description || '';
  form.elements.q.value = filters.q || '';
  form.elements.country.value = filters.country || '';
  form.elements.min_score.value = filters.min_score ?? '';
  form.elements.posted_within_days.value = filters.posted_within_days ?? '';
  form.elements.remote_only.checked = filters.remote_only;
  form.elements.is_active.checked = search.is_active;
  form.elements.is_default.checked = search.is_default;
  saveButton.textContent = 'Update route';
  cancelEdit.hidden = false;
  document.querySelector('#route-form-title').textContent = `Edit ${search.name}`;
  form.elements.name.focus();
}

function formPayload() {
  const numberOrNull = (value) => value === '' ? null : Number(value);
  return {
    name: form.elements.name.value,
    description: form.elements.description.value || null,
    filters: {
      q: form.elements.q.value || null,
      country: form.elements.country.value || null,
      remote_only: form.elements.remote_only.checked,
      min_score: numberOrNull(form.elements.min_score.value),
      posted_within_days: numberOrNull(form.elements.posted_within_days.value),
      active: true,
      discarded: false,
      application_state: 'none',
      include_duplicates: false,
    },
    sort_by: 'ranking_score',
    sort_order: 'desc',
    is_active: form.elements.is_active.checked,
    is_default: form.elements.is_default.checked,
  };
}

function matchMarkup(job) {
  return `<article class="daily-match"><div><span class="utility-label">${esc(job.source?.ats || job.source_slug)} / ${esc(relativeDate(job.first_seen_at))}</span><h3><a href="/app/job-detail.html?id=${job.id}">${esc(job.title)}</a></h3><p>${esc(job.company_name)} · ${esc(job.location || 'Location not listed')} · ${esc(salary(job))}</p></div><strong class="daily-match-score">${score(job.ranking_score)}</strong></article>`;
}

async function loadMatches() {
  if (!selectedId) return;
  matchesSection.hidden = false;
  matchesHost.innerHTML = '<p class="loading-note">Reading route matches…</p>';
  try {
    const payload = await api.savedSearchMatches(selectedId, { limit: 100, new_only: newOnly.checked });
    matchTitle.textContent = `${payload.saved_search.name} · ${payload.total} match${payload.total === 1 ? '' : 'es'}`;
    if (!payload.items.length) renderEmpty(matchesHost, newOnly.checked ? 'No new matches' : 'No route matches', newOnly.checked ? 'This route is caught up.' : 'Edit the route to broaden its filters.');
    else matchesHost.innerHTML = payload.items.map(matchMarkup).join('');
  } catch (error) {
    renderError(matchesHost, error, loadMatches);
  }
}

async function loadSearches() {
  try {
    searches = await api.savedSearches({ include_counts: true });
    if (selectedId && !searches.some((item) => item.id === selectedId)) selectedId = null;
    renderSearches();
    if (selectedId) await loadMatches();
    message.textContent = `${searches.length} saved route${searches.length === 1 ? '' : 's'}.`;
  } catch (error) {
    renderError(listHost, error, loadSearches);
    message.textContent = 'Saved routes could not be loaded.';
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  setBusy(saveButton, true);
  try {
    const id = Number(form.elements.id.value) || null;
    if (id) await api.updateSavedSearch(id, formPayload());
    else await api.createSavedSearch(formPayload());
    makeToast(id ? 'Route updated.' : 'Route saved.');
    resetForm();
    await loadSearches();
  } catch (error) {
    makeToast(error.message, 'error');
  } finally {
    setBusy(saveButton, false);
  }
});

listHost.addEventListener('click', async (event) => {
  const card = event.target.closest('[data-search-id]');
  const button = event.target.closest('button');
  if (!card || !button) return;
  const id = Number(card.dataset.searchId);
  const search = searches.find((item) => item.id === id);
  if (button.matches('[data-open]')) {
    selectedId = id;
    window.history.replaceState({}, '', `${window.location.pathname}?search=${id}`);
    renderSearches();
    await loadMatches();
    matchesSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  if (button.matches('[data-edit]')) editSearch(search);
  if (button.matches('[data-delete]') && window.confirm(`Delete “${search.name}”?`)) {
    setBusy(button, true);
    try {
      await api.deleteSavedSearch(id);
      if (selectedId === id) {
        selectedId = null;
        matchesSection.hidden = true;
      }
      makeToast('Route deleted.');
      await loadSearches();
    } catch (error) {
      makeToast(error.message, 'error');
      setBusy(button, false);
    }
  }
});

markReviewed.addEventListener('click', async () => {
  if (!selectedId) return;
  setBusy(markReviewed, true);
  try {
    await api.markSavedSearchReviewed(selectedId);
    makeToast('Route marked reviewed.');
    newOnly.checked = false;
    await loadSearches();
  } catch (error) {
    makeToast(error.message, 'error');
  } finally {
    setBusy(markReviewed, false);
  }
});

newOnly.addEventListener('change', loadMatches);
cancelEdit.addEventListener('click', resetForm);
loadSearches();
