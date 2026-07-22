import '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { absoluteDate, escapeHtml as esc, label, safeUrl, score } from '../format.js?v=20260721-1';
import { loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const queue = document.querySelector('[data-queue]');
const comparison = document.querySelector('[data-comparison]');
let cases = [];
let selectedId;

function renderQueue() {
  queue.replaceChildren();
  const header = document.createElement('div');
  header.className = 'kit-head';
  header.innerHTML = `<div><p class="utility-label">Open review queue</p><h2>${cases.length} case${cases.length === 1 ? '' : 's'}</h2></div>`;
  queue.append(header);
  cases.forEach((item, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `queue-item${item.id === selectedId ? ' is-active' : ''}`;
    button.innerHTML = `<small>Case ${String(index + 1).padStart(2, '0')} · ${esc(label(item.status))}</small><strong>${esc(item.candidate_job.title)}</strong><small>${esc(item.candidate_job.company_name)} · 2 records</small>`;
    button.addEventListener('click', () => { selectedId = item.id; renderQueue(); renderComparison(); });
    queue.append(button);
  });
}

function signals(item) {
  const entries = Object.entries(item.signals_json || {});
  if (!entries.length) return '<p>No structured confidence signals were recorded.</p>';
  return `<dl class="signal-list">${entries.map(([key, value]) => `<div><dt>${esc(label(key))}</dt><dd>${esc(typeof value === 'object' ? JSON.stringify(value) : value)}</dd></div>`).join('')}</dl>`;
}

function sheet(job, name) {
  const apply = safeUrl(job.apply_url);
  return `<article class="record-sheet"><p class="utility-label">${esc(name)} / Job #${job.id}</p><h2>${esc(job.title)}</h2><div class="action-row"><span class="tag">${esc(label(job.source_slug))}</span><span class="tag">${job.active ? 'Active' : 'Inactive'}</span><span class="tag">${score(job.ranking_score)} match</span></div><div class="evidence-row evidence-match"><small>Company</small><span>${esc(job.company_name)}</span></div><div class="evidence-row"><small>Location</small><span>${esc(job.location || 'Not listed')}</span></div><div class="evidence-row"><small>Current duplicate status</small><span>${esc(label(job.duplicate_status))}</span></div><div class="evidence-row"><small>Canonical apply URL</small><span>${apply ? `<a href="${esc(apply)}" target="_blank" rel="noopener noreferrer">${esc(apply)}</a>` : 'Not supplied'}</span></div><div class="evidence-row"><small>First seen</small><span>${esc(absoluteDate(job.first_seen_at))}</span></div><div class="evidence-row"><small>Last seen</small><span>${esc(absoluteDate(job.last_seen_at))}</span></div></article>`;
}

function renderComparison() {
  const item = cases.find((entry) => entry.id === selectedId);
  if (!item) { renderEmpty(comparison, 'No open duplicate reviews', 'Conservative matching has no uncertain record pairs waiting for a decision.'); return; }
  comparison.innerHTML = `<i class="registration-mark mark-tl" aria-hidden="true"></i><i class="registration-mark mark-tr" aria-hidden="true"></i><i class="registration-mark mark-bl" aria-hidden="true"></i><i class="registration-mark mark-br" aria-hidden="true"></i><header class="comparison-head"><div><p class="utility-label">Case #${item.id} / ${esc(item.reason)}</p><h2>Are these the same posting?</h2></div><span class="tag">${esc(label(item.status))}</span></header><section class="signal-sheet"><h3>Confidence and recorded signals</h3>${signals(item)}</section><div class="comparison-grid">${sheet(item.candidate_job, 'Record A / Candidate')}${sheet(item.existing_job, 'Record B / Existing')}</div><footer class="comparison-actions"><label class="resolution-field"><span class="field-label">Resolution note (optional)</span><input class="text-input" data-notes placeholder="Why did you make this decision?"></label><div class="action-row"><button class="button button-quiet" type="button" data-decision="dismissed">Defer</button><button class="button" type="button" data-decision="not_duplicate">Keep separate</button><button class="button button-primary" type="button" data-decision="merged">Merge records</button></div><p class="form-status" data-status aria-live="polite"></p></footer>`;
  comparison.querySelectorAll('[data-decision]').forEach((button) => button.addEventListener('click', () => decide(item, button.dataset.decision, button)));
}

async function decide(item, decision, button) {
  const status = comparison.querySelector('[data-status]');
  setBusy(button, true);
  status.textContent = 'Recording decision…';
  try {
    await api.updateDuplicate(item.id, { status: decision, resolution_notes: comparison.querySelector('[data-notes]').value.trim() || null });
    cases = cases.filter((entry) => entry.id !== item.id);
    selectedId = cases[0]?.id;
    renderQueue();
    renderComparison();
    makeToast(`Review marked ${label(decision).toLowerCase()}.`);
  } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); setBusy(button, false); }
}

async function load() {
  loading(queue, 'Reading the duplicate review queue…');
  loading(comparison, 'Preparing comparison sheets…');
  try { cases = await api.duplicates('open'); selectedId = cases[0]?.id; renderQueue(); renderComparison(); } catch (error) { renderError(queue, error, load); comparison.replaceChildren(); }
}
load();
