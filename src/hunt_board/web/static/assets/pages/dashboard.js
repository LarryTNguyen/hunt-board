import '../navigation.js?v=20260727-5';
import { api } from '../api.js?v=20260727-5';
import { escapeHtml as esc, relativeDate, salary, score } from '../format.js?v=20260721-2';
import { makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const message = document.querySelector('[data-dashboard-message]');
const freshnessHost = document.querySelector('[data-freshness-content]');
const totalsHost = document.querySelector('[data-totals-content]');
const searchesHost = document.querySelector('[data-search-content]');
const matchesHost = document.querySelector('[data-match-content]');
const pipelineHost = document.querySelector('[data-pipeline-content]');
const followupHost = document.querySelector('[data-followup-content]');

function routeHref(search) {
  return `/app/saved-searches.html?search=${search.id}`;
}

function renderFreshness(freshness) {
  const tone = freshness.status === 'ok' ? 'tone-positive' : 'tone-negative';
  freshnessHost.innerHTML = `<div class="freshness-banner ${tone}">
    <div><span class="status ${freshness.status === 'ok' ? '' : 'status-new'}">${esc(freshness.status)}</span><strong>${freshness.run_in_progress ? 'Refresh in progress' : freshness.status === 'ok' ? 'Sources reporting normally' : 'Source attention needed'}</strong></div>
    <dl><div><dt>Last success</dt><dd>${esc(freshness.last_successful_at ? relativeDate(freshness.last_successful_at) : 'Not recorded')}</dd></div><div><dt>Due sources</dt><dd>${freshness.due_sources}</dd></div><div><dt>Unhealthy</dt><dd>${freshness.unhealthy_sources}</dd></div></dl>
  </div>`;
}

function renderTotals(totals) {
  const items = [
    ['New in 24 hours', totals.jobs_first_seen_last_24_hours],
    ['New in 7 days', totals.jobs_first_seen_last_7_days],
    ['New route matches', totals.saved_search_new_matches],
    ['Saved jobs', totals.saved_jobs],
    ['Active applications', totals.active_applications],
    ['Unread inbox', totals.unread_notifications],
  ];
  totalsHost.innerHTML = items.map(([label, value]) => `<div><small>${esc(label)}</small><strong>${value}</strong></div>`).join('');
}

function renderSearches(searches) {
  if (!searches.length) {
    const link = Object.assign(document.createElement('a'), { className: 'button button-primary', href: '/app/saved-searches.html', textContent: 'Create a route' });
    renderEmpty(searchesHost, 'No active routes yet', 'Save a discovery route to make this dashboard personal.', link);
    return;
  }
  searchesHost.innerHTML = searches.map((search) => `<article class="route-card ${search.is_default ? 'is-default' : ''}">
    <div class="route-card-head"><span class="utility-label">${search.is_default ? 'Default route' : 'Saved route'}</span><span>${search.new_since_review_count} new</span></div>
    <h3><a href="${routeHref(search)}">${esc(search.name)}</a></h3>
    <p>${esc(search.description || 'No route note yet.')}</p>
    <dl><div><dt>Matches</dt><dd>${search.match_count}</dd></div><div><dt>Last reviewed</dt><dd>${esc(search.last_viewed_at ? relativeDate(search.last_viewed_at) : 'Never')}</dd></div></dl>
  </article>`).join('');
}

function matchCard(job) {
  return `<article class="daily-match" data-job-id="${job.id}">
    <div><span class="utility-label">${esc(job.source?.ats || job.source_slug)} / ${esc(relativeDate(job.first_seen_at))}</span><h3><a href="/app/job-detail.html?id=${job.id}">${esc(job.title)}</a></h3><p>${esc(job.company_name)} · ${esc(job.location || 'Location not listed')} · ${esc(salary(job))}</p></div>
    <strong class="daily-match-score">${score(job.ranking_score)}</strong>
    <div class="action-row">${job.is_saved ? '<button class="button button-quiet" type="button" data-unsave>Unsave</button>' : '<button class="button" type="button" data-save>Save</button>'}${job.has_application ? '<span class="tag">Tracked</span>' : '<button class="button button-dark" type="button" data-track>Add to tracker</button>'}<button class="button button-quiet" type="button" data-discard>Hide</button></div>
  </article>`;
}

function renderMatches(matches) {
  if (!matches.length) {
    renderEmpty(matchesHost, 'No new route matches', 'You are caught up. New jobs will appear here after the next successful ingestion.');
    return;
  }
  matchesHost.innerHTML = matches.map(matchCard).join('');
}

function renderPipeline(items) {
  pipelineHost.innerHTML = `<ol class="pipeline-list">${items.map((item) => `<li><span>${esc(item.name)}</span><strong>${item.count}</strong></li>`).join('')}</ol>`;
}

function renderFollowups(items) {
  if (!items.length) {
    renderEmpty(followupHost, 'No follow-ups are overdue', 'Non-terminal applications appear here after seven quiet days.');
    return;
  }
  followupHost.innerHTML = `<ul class="followup-list">${items.map((item) => `<li><div><a href="/app/application-tracker.html">${esc(item.job.title)}</a><small>${esc(item.job.company_name)} · ${esc(item.status.name)}</small></div><span>${esc(relativeDate(item.updated_at))}</span></li>`).join('')}</ul>`;
}

async function handleMatchAction(event) {
  const button = event.target.closest('button');
  const card = event.target.closest('[data-job-id]');
  if (!button || !card) return;
  const jobId = Number(card.dataset.jobId);
  setBusy(button, true);
  try {
    if (button.matches('[data-save]')) await api.saveJob(jobId);
    if (button.matches('[data-unsave]')) await api.unsaveJob(jobId);
    if (button.matches('[data-track]')) await api.createApplication(jobId);
    if (button.matches('[data-discard]')) await api.discardJob(jobId);
    await loadDashboard();
  } catch (error) {
    makeToast(error.message, 'error');
    setBusy(button, false);
  }
}

async function loadDashboard() {
  message.textContent = 'Preparing today’s field report…';
  try {
    const payload = await api.dailyDashboard();
    renderFreshness(payload.freshness);
    renderTotals(payload.totals);
    renderSearches(payload.saved_searches);
    renderMatches(payload.top_new_matches);
    renderPipeline(payload.application_pipeline);
    renderFollowups(payload.follow_up_candidates);
    message.textContent = `Field report updated ${relativeDate(payload.generated_at)}.`;
  } catch (error) {
    message.textContent = 'The daily report could not be loaded.';
    renderError(freshnessHost, error, loadDashboard);
  }
}

matchesHost.addEventListener('click', handleMatchAction);
loadDashboard();
