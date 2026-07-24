import '../navigation.js?v=20260722-4';
import { api } from '../api.js?v=20260722-4';
import { absoluteDate, escapeHtml as esc, label, relativeDate } from '../format.js?v=20260721-2';
import { loading, makeToast, renderEmpty, renderError } from '../ui.js?v=20260721-1';

const statusHost = document.querySelector('[data-system-status]');
const sourceBoard = document.querySelector('[data-source-board]');
const sourceCount = document.querySelector('[data-source-count]');
const runList = document.querySelector('[data-run-list]');
const runDetail = document.querySelector('[data-run-detail]');
const message = document.querySelector('[data-operation-message]');
let operations = null;
let selectedRunId = null;

function tone(status) {
  if (['completed', 'healthy'].includes(status)) return 'positive';
  if (['failed', 'abandoned', 'unhealthy', 'completed_with_errors'].includes(status)) return 'negative';
  if (status === 'running') return 'active';
  return 'neutral';
}

function renderSystemStatus() {
  const ingestion = operations.ingestion;
  const cards = [
    ['Run state', ingestion.run_in_progress ? 'In progress' : 'Idle', ingestion.run_in_progress ? 'active' : 'positive'],
    ['Last successful refresh', relativeDate(ingestion.last_successful_at, 'None recorded'), 'neutral'],
    ['Next source due', relativeDate(ingestion.next_due_at, 'No enabled source due'), 'neutral'],
    ['Active jobs', operations.jobs.active.toLocaleString(), 'neutral'],
    ['Unhealthy sources', operations.sources.unhealthy.toLocaleString(), operations.sources.unhealthy ? 'negative' : 'positive'],
  ];
  statusHost.innerHTML = cards.map(([name, value, cardTone]) => `<article class="operation-stat tone-${cardTone}"><small>${esc(name)}</small><strong>${esc(value)}</strong></article>`).join('');
  statusHost.setAttribute('aria-busy', 'false');
}

function renderSources() {
  const sources = operations.sources.items;
  sourceCount.textContent = `${operations.sources.enabled} enabled / ${operations.sources.total} configured`;
  sourceBoard.setAttribute('aria-busy', 'false');
  if (!sources.length) {
    renderEmpty(sourceBoard, 'No sources are configured', 'Sync the YAML source registry to populate the board.');
    return;
  }
  sourceBoard.innerHTML = sources.map((source) => `<article class="source-record tone-${tone(source.health_status)}">
    <div class="source-record-head"><div><span class="source-tag">${esc(source.ats)}</span><h3>${esc(source.company_name)}</h3><p>${esc(source.slug)}</p></div><span class="status ${source.health_status === 'healthy' ? '' : 'status-new'}">${source.enabled ? esc(label(source.health_status)) : 'Disabled'}</span></div>
    <dl class="source-metrics"><div><dt>Last checked</dt><dd>${esc(relativeDate(source.last_checked_at, 'Never'))}</dd></div><div><dt>Last success</dt><dd>${esc(relativeDate(source.last_successful_at, 'Never'))}</dd></div><div><dt>Next due</dt><dd>${esc(relativeDate(source.next_due_at, 'Now'))}</dd></div><div><dt>Failures</dt><dd>${source.consecutive_failures}</dd></div><div><dt>Poll interval</dt><dd>${source.poll_interval_minutes || '—'} min</dd></div><div><dt>Close after</dt><dd>${source.close_after_missed_runs} misses</dd></div></dl>
    ${source.last_error ? `<p class="source-error" role="status">${esc(source.last_error)}</p>` : ''}
    <div class="action-row"><button class="button button-quiet" type="button" data-source-dry="${source.id}" data-operation-action>Dry run</button><button class="button" type="button" data-source-real="${source.id}" data-source-name="${esc(source.company_name)}" data-operation-action>Run source</button></div>
  </article>`).join('');
}

function renderRuns() {
  runList.setAttribute('aria-busy', 'false');
  if (!operations.recent_runs.length) {
    renderEmpty(runList, 'No ingestion runs yet', 'Run due sources to create the first operational record.');
    runDetail.innerHTML = '<p>Source metrics will appear after a run is selected.</p>';
    return;
  }
  runList.innerHTML = operations.recent_runs.map((run) => `<button class="run-record ${run.id === selectedRunId ? 'is-selected' : ''}" type="button" data-run-id="${run.id}"><span class="status status-${tone(run.status)}">${esc(label(run.status))}</span><strong>Run #${run.id}</strong><small>${esc(absoluteDate(run.started_at))}</small><span>${run.total_jobs_seen} jobs / ${run.total_errors} errors</span></button>`).join('');
}

async function selectRun(runId) {
  selectedRunId = runId;
  renderRuns();
  loading(runDetail, `Reading source metrics for run ${runId}…`);
  try {
    const items = await api.scrapeRunSources(runId);
    if (!items.length) {
      renderEmpty(runDetail, 'No source records', 'This run did not inspect a source.');
      return;
    }
    runDetail.innerHTML = `<div class="run-detail-head"><p class="utility-label">Run #${runId}</p><h3>Source metrics</h3></div>${items.map((item) => `<article class="source-run"><div><strong>${esc(item.source_slug)}</strong><span class="status status-${tone(item.status)}">${esc(label(item.status))}</span></div><dl><div><dt>Seen</dt><dd>${item.jobs_seen}</dd></div><div><dt>New</dt><dd>${item.new_jobs}</dd></div><div><dt>Updated</dt><dd>${item.updated_jobs}</dd></div><div><dt>Unchanged</dt><dd>${item.unchanged_jobs}</dd></div><div><dt>Closed</dt><dd>${item.closed_jobs}</dd></div><div><dt>Duplicates</dt><dd>${item.duplicates_found}</dd></div><div><dt>Errors</dt><dd>${item.error_count}</dd></div><div><dt>Duration</dt><dd>${item.duration_ms ?? 0} ms</dd></div></dl>${item.error_message ? `<p class="source-error">${esc(item.error_message)}</p>` : ''}</article>`).join('')}`;
  } catch (error) {
    renderError(runDetail, error, () => selectRun(runId));
  }
}

function setActionsBusy(busy) {
  document.querySelectorAll('[data-operation-action]').forEach((control) => {
    control.disabled = busy;
    control.setAttribute('aria-busy', String(busy));
  });
}

async function perform(description, operation) {
  setActionsBusy(true);
  message.textContent = `${description}…`;
  try {
    const result = await operation();
    const status = result.status || 'completed';
    message.textContent = `${description}: ${label(status)}.`;
    makeToast(`${description} finished.`);
    await loadOperations();
  } catch (error) {
    message.textContent = error.status === 409 ? 'Another real ingestion run is already in progress. Try again after it finishes.' : error.message;
    makeToast(message.textContent, 'error');
  } finally {
    setActionsBusy(false);
  }
}

async function loadOperations() {
  statusHost.setAttribute('aria-busy', 'true');
  sourceBoard.setAttribute('aria-busy', 'true');
  runList.setAttribute('aria-busy', 'true');
  loading(statusHost, 'Reading system status…');
  loading(sourceBoard, 'Reading source board…');
  loading(runList, 'Reading recent runs…');
  try {
    operations = await api.operations();
    renderSystemStatus();
    renderSources();
    renderRuns();
    if (selectedRunId && operations.recent_runs.some((run) => run.id === selectedRunId)) selectRun(selectedRunId);
  } catch (error) {
    renderError(statusHost, error, loadOperations);
    renderError(sourceBoard, error, loadOperations);
    renderError(runList, error, loadOperations);
  }
}

document.querySelector('[data-refresh]').addEventListener('click', loadOperations);
document.querySelector('[data-run-dry]').addEventListener('click', () => perform('Dry run due sources', () => api.runDueSources(true)));
document.querySelector('[data-run-real]').addEventListener('click', () => {
  if (window.confirm('Run all enabled sources that are currently due? This writes refreshed job and run records.')) perform('Run due sources', () => api.runDueSources(false));
});
document.querySelector('[data-sync]').addEventListener('click', () => perform('Sync YAML sources', api.syncSources));
sourceBoard.addEventListener('click', (event) => {
  const dry = event.target.closest('[data-source-dry]');
  const real = event.target.closest('[data-source-real]');
  if (dry) perform('Dry run source', () => api.runSource(dry.dataset.sourceDry, true));
  if (real && window.confirm(`Run ${real.dataset.sourceName} now, even if it is not due? This writes refreshed job and run records.`)) perform(`Run ${real.dataset.sourceName}`, () => api.runSource(real.dataset.sourceReal, false));
});
runList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-run-id]');
  if (button) selectRun(Number(button.dataset.runId));
});

loadOperations();
