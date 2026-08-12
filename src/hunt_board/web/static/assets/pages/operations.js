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
const invitationList = document.querySelector('[data-invitation-list]');
const invitationForm = document.querySelector('[data-invitation-form]');
const deploymentHost = document.querySelector('[data-deployment]');
const queueHost = document.querySelector('[data-queue-state]');
const metricsHost = document.querySelector('[data-operations-metrics]');
const quarantineList = document.querySelector('[data-quarantine-list]');
const quarantineCount = document.querySelector('[data-quarantine-count]');
const correlationForm = document.querySelector('[data-correlation-form]');
const correlationResults = document.querySelector('[data-correlation-results]');
let operations = null;
let selectedRunId = null;

function renderInvitations(items) {
  if (!items.length) {
    renderEmpty(invitationList, 'No invitations yet', 'Create the first exact-email beta invitation.');
    return;
  }
  invitationList.innerHTML = items.map((item) => `<article class="invitation-row">
    <div><strong>${esc(item.normalized_email)}</strong><small>${esc(label(item.status))} · ${esc(absoluteDate(item.created_at))}</small></div>
    ${item.status === 'pending' ? `<button class="button button-quiet" type="button" data-revoke-invitation="${item.id}">Revoke</button>` : ''}
  </article>`).join('');
}

async function loadInvitations() {
  loading(invitationList, 'Reading invitation ledger…');
  try {
    renderInvitations(await api.invitations());
  } catch (error) {
    renderError(invitationList, error, loadInvitations);
  }
}

function tone(status) {
  if (['completed', 'healthy'].includes(status)) return 'positive';
  if (['failed', 'abandoned', 'unhealthy', 'completed_with_errors', 'cancelled'].includes(status)) return 'negative';
  if (['running', 'pending', 'quarantined'].includes(status)) return 'active';
  return 'neutral';
}

function renderDeploymentAndQueue() {
  const deploy = operations.deployment;
  deploymentHost.innerHTML = `<strong>${esc(deploy.environment.toUpperCase())}</strong><span>Release ${esc(deploy.release)}</span><span>Deploy ${esc(deploy.deployment_id)}</span><span class="health-pair"><i></i> Web ${esc(deploy.web)} · DB ${esc(deploy.database)}</span>`;
  const ingestion = operations.ingestion;
  const active = ingestion.active_run_id
    ? `<article class="queue-node is-active"><small>Active</small><strong>Run #${ingestion.active_run_id}</strong><button class="button button-quiet" type="button" data-cancel-run="${ingestion.active_run_id}">Cancel</button></article>`
    : '<article class="queue-node"><small>Active</small><strong>Idle</strong></article>';
  const pending = ingestion.pending_run_id
    ? `<article class="queue-node is-pending"><small>Pending</small><strong>Run #${ingestion.pending_run_id}</strong><button class="button button-quiet" type="button" data-cancel-run="${ingestion.pending_run_id}">Cancel</button></article>`
    : '<article class="queue-node"><small>Pending</small><strong>Empty</strong></article>';
  const joined = `<article class="queue-node"><small>Joined requests</small><strong>${ingestion.pending_coalesced_triggers}</strong></article>`;
  queueHost.innerHTML = `${active}<span aria-hidden="true">→</span>${pending}<span aria-hidden="true">→</span>${joined}`;
  const metrics = operations.metrics;
  const cards = [
    ['Runs', metrics.runs_last_24_hours],
    ['Failed / degraded', metrics.failed_runs_last_24_hours],
    ['Retries', metrics.retries_last_24_hours],
    ['Timeouts', metrics.timeouts_last_24_hours],
    ['Pending quarantines', metrics.quarantines_pending],
    ['Average source time', `${metrics.average_source_duration_ms} ms`],
  ];
  metricsHost.innerHTML = cards.map(([name, value]) => `<article class="operation-stat"><small>${esc(name)}</small><strong>${esc(value)}</strong></article>`).join('');
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
  runList.innerHTML = operations.recent_runs.map((run) => `<article class="run-record ${run.id === selectedRunId ? 'is-selected' : ''}"><button class="run-record-main" type="button" data-run-id="${run.id}"><span class="status status-${tone(run.status)}">${esc(label(run.status))}</span><strong>Run #${run.id}</strong><small>${esc(absoluteDate(run.started_at))}</small><span>${run.total_jobs_seen} jobs / ${run.total_errors} errors</span><code>${esc(run.trace_id || run.request_id || 'No trace ID')}</code></button><div class="run-record-actions">${['failed', 'completed_with_errors', 'abandoned'].includes(run.status) ? `<button class="button button-quiet" type="button" data-retry-run="${run.id}">Retry failed</button>` : ''}${['running', 'pending'].includes(run.status) ? `<button class="button button-quiet" type="button" data-cancel-run="${run.id}">Cancel</button>` : ''}</div></article>`).join('');
}

async function loadQuarantines() {
  try {
    const items = await api.quarantines('pending');
    quarantineCount.textContent = `${items.length} awaiting decision`;
    if (!items.length) {
      renderEmpty(quarantineList, 'No suspicious changes waiting', 'Quarantined scan results appear here before destructive reconciliation.');
      return;
    }
    quarantineList.innerHTML = items.map((item) => `<article class="quarantine-record"><div><span class="status status-active">Quarantined</span><h3>${esc(item.source_slug)}</h3><p>${esc(item.reason)}</p><small>Run #${item.scrape_run_id} · ${esc(absoluteDate(item.created_at))}</small></div><dl>${Object.entries(item.diff_summary).map(([key, value]) => `<div><dt>${esc(label(key))}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><div class="action-row"><button class="button button-primary" type="button" data-approve-quarantine="${item.id}">Approve and rescan</button><button class="button button-quiet" type="button" data-reject-quarantine="${item.id}">Reject result</button></div></article>`).join('');
  } catch (error) {
    renderError(quarantineList, error, loadQuarantines);
  }
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
    runDetail.innerHTML = `<div class="run-detail-head"><p class="utility-label">Run #${runId}</p><h3>Source metrics</h3></div>${items.map((item) => `<article class="source-run"><div><strong>${esc(item.source_slug)}</strong><span class="status status-${tone(item.status)}">${esc(label(item.status))}</span></div><dl><div><dt>Seen</dt><dd>${item.jobs_seen}</dd></div><div><dt>New</dt><dd>${item.new_jobs}</dd></div><div><dt>Updated</dt><dd>${item.updated_jobs}</dd></div><div><dt>Reactivated</dt><dd>${item.reactivated_jobs}</dd></div><div><dt>Closed</dt><dd>${item.closed_jobs}</dd></div><div><dt>Retries</dt><dd>${item.retry_count}</dd></div><div><dt>Timeouts</dt><dd>${item.timeout_count}</dd></div><div><dt>Parser failures</dt><dd>${item.parser_failure_count}</dd></div><div><dt>Duplicates</dt><dd>${item.duplicates_found}</dd></div><div><dt>Errors</dt><dd>${item.error_count}</dd></div><div><dt>Duration</dt><dd>${item.duration_ms ?? 0} ms</dd></div></dl>${item.error_message ? `<p class="source-error">${esc(item.error_message)}</p>` : ''}</article>`).join('')}`;
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
    renderDeploymentAndQueue();
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
document.querySelector('[data-recover]').addEventListener('click', () => perform('Recover stale runs', api.recoverStaleRuns));
queueHost.addEventListener('click', (event) => {
  const cancel = event.target.closest('[data-cancel-run]');
  if (cancel && window.confirm(`Cancel run #${cancel.dataset.cancelRun}?`)) perform(`Cancel run #${cancel.dataset.cancelRun}`, () => api.cancelRun(cancel.dataset.cancelRun));
});
sourceBoard.addEventListener('click', (event) => {
  const dry = event.target.closest('[data-source-dry]');
  const real = event.target.closest('[data-source-real]');
  if (dry) perform('Dry run source', () => api.runSource(dry.dataset.sourceDry, true));
  if (real && window.confirm(`Run ${real.dataset.sourceName} now, even if it is not due? This writes refreshed job and run records.`)) perform(`Run ${real.dataset.sourceName}`, () => api.runSource(real.dataset.sourceReal, false));
});
runList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-run-id]');
  if (button) selectRun(Number(button.dataset.runId));
  const retry = event.target.closest('[data-retry-run]');
  if (retry) perform(`Retry failed companies from run #${retry.dataset.retryRun}`, () => api.retryFailedSources(retry.dataset.retryRun));
  const cancel = event.target.closest('[data-cancel-run]');
  if (cancel && window.confirm(`Cancel run #${cancel.dataset.cancelRun}?`)) perform(`Cancel run #${cancel.dataset.cancelRun}`, () => api.cancelRun(cancel.dataset.cancelRun));
});
quarantineList.addEventListener('click', async (event) => {
  const approve = event.target.closest('[data-approve-quarantine]');
  const reject = event.target.closest('[data-reject-quarantine]');
  if (approve && window.confirm('Approve this result and immediately rescan the source?')) {
    await perform('Approve quarantine and rescan', () => api.approveQuarantine(approve.dataset.approveQuarantine));
    await loadQuarantines();
  }
  if (reject && window.confirm('Reject this source result? No job lifecycle evidence will be applied.')) {
    await perform('Reject quarantine', () => api.rejectQuarantine(reject.dataset.rejectQuarantine));
    await loadQuarantines();
  }
});
correlationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loading(correlationResults, 'Finding correlated run metadata…');
  try {
    const result = await api.correlationLookup(new FormData(correlationForm).get('identifier'));
    if (!result.runs.length) {
      renderEmpty(correlationResults, 'No run metadata found', 'Search your log or trace provider for the exact ID, or verify the value.');
      return;
    }
    correlationResults.innerHTML = result.runs.map((run) => `<article class="correlation-result"><strong>Run #${run.run_id}</strong><span>${esc(label(run.status))}</span><code>${esc(run.request_id || 'No request ID')}</code><code>${esc(run.trace_id || 'No trace ID')}</code></article>`).join('');
  } catch (error) {
    renderError(correlationResults, error, () => correlationForm.requestSubmit());
  }
});
invitationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = invitationForm.querySelector('button');
  button.disabled = true;
  try {
    await api.createInvitation(new FormData(invitationForm).get('email'));
    invitationForm.reset();
    makeToast('Invitation created.');
    await loadInvitations();
  } catch (error) {
    makeToast(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});
invitationList.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-revoke-invitation]');
  if (!button || !window.confirm('Revoke this pending invitation?')) return;
  button.disabled = true;
  try {
    await api.revokeInvitation(button.dataset.revokeInvitation);
    makeToast('Invitation revoked.');
    await loadInvitations();
  } catch (error) {
    makeToast(error.message, 'error');
    button.disabled = false;
  }
});

loadOperations();
loadInvitations();
loadQuarantines();
