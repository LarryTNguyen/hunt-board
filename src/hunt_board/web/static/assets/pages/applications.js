import '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { absoluteDate, activateCompanyLogos, companyMark, country, escapeHtml as esc, label, relativeDate, salary } from '../format.js?v=20260721-2';
import { debounce, loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const host = document.querySelector('[data-tracker]');
const search = document.querySelector('[data-search]');
const statusFilter = document.querySelector('[data-status]');
const dateFilter = document.querySelector('[data-date]');
const count = document.querySelector('[data-count]');
const dialog = document.querySelector('[data-dialog]');
const dialogContent = document.querySelector('[data-dialog-content]');
let applications = [];
let statuses = [];

function statusTone(slug) {
  if (['rejection'].includes(slug)) return 'status-tone-negative';
  if (['positive-hear-back', 'offer-received'].includes(slug)) return 'status-tone-positive';
  if (['ghosted', 'withdrawn'].includes(slug)) return 'status-tone-muted';
  if (['oa-received', 'interview-scheduled'].includes(slug)) return 'status-tone-active';
  return 'status-tone-neutral';
}

function filtered() {
  const term = search.value.trim().toLowerCase();
  const days = Number(dateFilter.value);
  const cutoff = days ? Date.now() - days * 86400000 : 0;
  return applications.filter((item) => {
    const statusMatch = statusFilter.value === 'all' || (statusFilter.value === 'terminal' ? item.status.is_terminal : item.status.slug === statusFilter.value);
    return `${item.job.title} ${item.job.company_name}`.toLowerCase().includes(term) && statusMatch && (!cutoff || new Date(item.updated_at).valueOf() >= cutoff);
  });
}

function render() {
  const items = filtered();
  count.textContent = `${items.length} application${items.length === 1 ? '' : 's'}`;
  if (!items.length) {
    const button = Object.assign(document.createElement('button'), { className: 'button button-primary', type: 'button', textContent: 'Add an application' });
    button.addEventListener('click', openAddDialog);
    renderEmpty(host, applications.length ? 'No frames match these filters' : 'No applications are in motion', applications.length ? 'Change the stage, date, or search filter.' : 'Start from a Hunt Board job record to add the first frame.', button);
    return;
  }
  const roll = document.createElement('div');
  roll.className = 'film-roll live-film-roll';
  const table = document.createElement('div');
  table.className = 'film-table live-film-table';
  table.innerHTML = '<div class="film-head"><span>Job / Company</span><span>Location</span><span>Stage</span><span>Date applied</span><span>Updated</span><span>Notes</span><span>Timeline</span></div>';
  items.forEach((item) => {
    const row = document.createElement('article');
    row.className = `film-row live-film-row ${statusTone(item.status.slug)}`;
    row.innerHTML = `<a class="film-cell film-role film-role-link" href="/app/job-detail.html?v=20260721-1&id=${item.job.id}" aria-label="Open dossier for ${esc(item.job.title)} at ${esc(item.job.company_name)}"><div class="company-lockup">${companyMark(item.job.company_name, item.job.company_logo_url)}<span><strong class="company-name">${esc(item.job.company_name)}</strong><span class="role-title">${esc(item.job.title)}</span><small>Open job dossier ↗</small></span></div></a>
      <div class="film-cell"><small>Location</small><strong>${esc(item.job.location || 'Not listed')}</strong><span class="film-subvalue">${esc(country(item.job))}</span><span class="film-subvalue">${esc(salary(item.job))}</span></div>
      <div class="film-cell"><label class="sr-only" for="status-${item.id}">Stage for ${esc(item.job.company_name)}</label><select class="film-edit-control" id="status-${item.id}" data-stage>${statuses.map((status) => `<option value="${esc(status.slug)}"${status.slug === item.status.slug ? ' selected' : ''}>${esc(status.name)}</option>`).join('')}</select></div>
      <div class="film-cell"><small>Started</small><strong>${esc(absoluteDate(item.created_at))}</strong></div>
      <div class="film-cell"><small>Last movement</small><strong>${esc(relativeDate(item.updated_at))}</strong></div>
      <div class="film-cell"><small>Field note</small><strong>${esc(item.notes || 'No note yet')}</strong></div>
      <div class="film-cell"><button class="button button-dark" type="button" data-open>Open frame</button><a class="text-button" href="/app/job-detail.html?v=20260721-1&id=${item.job.id}">Job dossier</a></div>`;
    row.querySelector('[data-stage]').addEventListener('change', (event) => updateStage(item, event.currentTarget));
    row.querySelector('[data-open]').addEventListener('click', () => openApplication(item));
    activateCompanyLogos(row);
    table.append(row);
  });
  roll.append(table);
  host.replaceChildren(roll);
}

async function updateStage(item, select) {
  const old = item.status.slug;
  setBusy(select, true);
  try {
    const updated = await api.updateApplication(item.id, { status: select.value, status_note: 'Stage updated from the live tracker' });
    Object.assign(item, updated);
    makeToast(`Application moved to ${updated.status.name}.`);
    render();
  } catch (error) { select.value = old; makeToast(error.message, 'error'); setBusy(select, false); }
}

function showDialog() {
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
}

function closeDialog() {
  if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open');
}

async function openApplication(item) {
  dialogContent.innerHTML = `<div class="dialog-head"><div><p class="utility-label">Application frame / #${item.id}</p><h2>${esc(item.job.title)}</h2><p>${esc(item.job.company_name)} · ${esc(item.status.name)}</p></div><button class="icon-button" type="button" data-close aria-label="Close application frame">×</button></div><div class="dialog-grid"><section><label class="field-label" for="application-notes">Application notes</label><textarea class="notes-area" id="application-notes">${esc(item.notes || '')}</textarea><div class="action-row"><button class="button button-primary" type="button" data-save-notes>Save notes</button><button class="button button-danger" type="button" data-delete>Remove from tracker</button></div><p class="form-status" data-note-status aria-live="polite"></p><hr><h3>Record a manual event</h3><form data-event-form><label class="field-label" for="event-type">Event type</label><select class="select-field full-field" id="event-type" name="event_type"><option value="note">Note</option><option value="follow_up">Follow up</option><option value="online_assessment">Online assessment</option><option value="interview">Interview</option><option value="recruiter_contact">Recruiter contact</option><option value="rejection">Rejection</option><option value="offer">Offer</option></select><label class="field-label" for="event-notes">Event notes</label><textarea class="text-area" id="event-notes" name="notes" required></textarea><label class="field-label" for="event-date">Occurred at (optional)</label><input class="text-input" id="event-date" name="occurred_at" type="datetime-local"><button class="button button-dark" type="submit">Add event</button><p class="form-status" data-event-status aria-live="polite"></p></form></section><section><p class="section-label">Timeline</p><div data-timeline></div></section></div>`;
  dialogContent.querySelector('[data-close]').addEventListener('click', closeDialog);
  dialogContent.querySelector('[data-save-notes]').addEventListener('click', (event) => saveNotes(item, event.currentTarget));
  dialogContent.querySelector('[data-delete]').addEventListener('click', (event) => removeApplication(item, event.currentTarget));
  dialogContent.querySelector('[data-event-form]').addEventListener('submit', (event) => addEvent(item, event));
  showDialog();
  await renderTimeline(item);
}

async function removeApplication(item, button) {
  if (!window.confirm(`Remove ${item.job.title} at ${item.job.company_name} from the tracker? Its application notes and timeline will also be removed.`)) return;
  setBusy(button, true);
  try {
    await api.deleteApplication(item.id);
    applications = applications.filter((application) => application.id !== item.id);
    closeDialog();
    render();
    makeToast('Application removed from the tracker. The job is available in discovery again.');
  } catch (error) {
    makeToast(error.message, 'error');
    setBusy(button, false);
  }
}

async function saveNotes(item, button) {
  const status = dialogContent.querySelector('[data-note-status]');
  setBusy(button, true);
  status.textContent = 'Saving notes…';
  try {
    const updated = await api.updateApplication(item.id, { notes: dialogContent.querySelector('#application-notes').value });
    Object.assign(item, updated);
    status.textContent = 'Notes saved.';
    makeToast('Application notes updated.');
    render();
  } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); }
  setBusy(button, false);
}

async function renderTimeline(item) {
  const timeline = dialogContent.querySelector('[data-timeline]');
  loading(timeline, 'Developing the event timeline…');
  try {
    const events = await api.events(item.id);
    if (!events.length) { renderEmpty(timeline, 'No events recorded', 'Add a note, interview, or follow-up to begin the trail.'); return; }
    timeline.innerHTML = events.slice().reverse().map((event) => `<article class="timeline-event"><span class="timeline-mark" aria-hidden="true"></span><div><p class="utility-label">${esc(label(event.event_type))} / ${esc(absoluteDate(event.occurred_at))}</p><h4>${esc(event.new_status ? `Moved to ${label(event.new_status)}` : label(event.event_type))}</h4><p>${esc(event.notes || 'No additional note')}</p></div></article>`).join('');
  } catch (error) { renderError(timeline, error, () => renderTimeline(item)); }
}

async function addEvent(item, event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const status = form.querySelector('[data-event-status]');
  setBusy(button, true);
  const occurred = form.elements.occurred_at.value;
  try {
    await api.createEvent(item.id, { event_type: form.elements.event_type.value, notes: form.elements.notes.value, ...(occurred ? { occurred_at: new Date(occurred).toISOString() } : {}) });
    form.reset();
    status.textContent = 'Event added.';
    makeToast('Timeline event recorded.');
    await renderTimeline(item);
  } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); }
  setBusy(button, false);
}

function openAddDialog() {
  dialogContent.innerHTML = `<div class="dialog-head"><div><p class="utility-label">New application / Choose a sighting</p><h2>Add an application</h2><p>Search existing Hunt Board job records, then start the tracker.</p></div><button class="icon-button" type="button" data-close aria-label="Close add application dialog">×</button></div><label class="search-field dialog-search"><span class="sr-only">Search job records</span><input type="search" data-job-search placeholder="Search by title or company"></label><div data-job-results class="dialog-results" aria-live="polite"></div>`;
  dialogContent.querySelector('[data-close]').addEventListener('click', closeDialog);
  dialogContent.querySelector('[data-job-search]').addEventListener('input', debounce(searchJobs, 300));
  renderEmpty(dialogContent.querySelector('[data-job-results]'), 'Search the sightings ledger', 'Enter a title or company to choose a job record.');
  showDialog();
  dialogContent.querySelector('[data-job-search]').focus();
}

async function searchJobs(event) {
  const term = event.target.value.trim();
  const target = dialogContent.querySelector('[data-job-results]');
  if (!term) { renderEmpty(target, 'Search the sightings ledger', 'Enter a title or company to choose a job record.'); return; }
  loading(target, 'Searching job records…');
  try {
    const jobs = (await api.jobs({ search: term, active: true, include_duplicates: false, limit: 20 })).filter((job) => !job.has_application);
    if (!jobs.length) { renderEmpty(target, 'No untracked jobs found', 'Try a broader search, or open discovery to review the route.'); return; }
    target.innerHTML = jobs.map((job) => `<button class="job-choice" type="button" data-job="${job.id}"><span><strong>${esc(job.title)}</strong><small>${esc(job.company_name)} · ${esc(job.location || 'Location not listed')}</small></span><span class="tag">Add</span></button>`).join('');
    target.querySelectorAll('[data-job]').forEach((button) => button.addEventListener('click', () => createFromJob(button.dataset.job, button)));
  } catch (error) { renderError(target, error); }
}

async function createFromJob(jobId, button) {
  setBusy(button, true);
  try { const created = await api.createApplication(jobId); closeDialog(); makeToast('Application added to the tracker.'); await load(); await openApplication(applications.find((item) => item.id === created.id) || created); } catch (error) { makeToast(error.message, 'error'); setBusy(button, false); }
}

async function load() {
  loading(host, 'Developing the application film roll…');
  try {
    [applications, statuses] = await Promise.all([api.applications(), api.statuses()]);
    statusFilter.replaceChildren(new Option('All stages', 'all'), new Option('Terminal stages', 'terminal'));
    statuses.forEach((status) => statusFilter.append(new Option(status.name, status.slug)));
    render();
    const requested = Number(new URLSearchParams(location.search).get('application'));
    if (requested) { const item = applications.find((entry) => entry.id === requested); if (item) openApplication(item); }
  } catch (error) { renderError(host, error, load); count.textContent = 'Applications unavailable'; }
}

document.querySelector('[data-add]').addEventListener('click', openAddDialog);
search.addEventListener('input', debounce(render, 180));
statusFilter.addEventListener('change', render);
dateFilter.addEventListener('change', render);
dialog.addEventListener('click', (event) => { if (event.target === dialog) closeDialog(); });
load();
