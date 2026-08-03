import '../navigation.js?v=20260731-1';
import { api } from '../api.js?v=20260731-1';
import { absoluteDate, companyMark, escapeHtml as esc, label, relativeDate } from '../format.js?v=20260721-2';
import { debounce, loading, makeToast, renderEmpty, renderError, setBusy } from '../ui.js?v=20260721-1';

const host = document.querySelector('[data-tracker]');
const search = document.querySelector('[data-search]');
const statusFilter = document.querySelector('[data-status]');
const dateFilter = document.querySelector('[data-date]');
const deletedToggle = document.querySelector('[data-deleted]');
const count = document.querySelector('[data-count]');
const dialog = document.querySelector('[data-dialog]');
const dialogContent = document.querySelector('[data-dialog-content]');
let applications = [];
let statuses = [];

function trackedJob(item) {
  return item.job || { id: null, ...item.manual_job, company_logo_url: null };
}

function filtered() {
  const term = search.value.trim().toLowerCase();
  const days = Number(dateFilter.value);
  const cutoff = days ? Date.now() - days * 86400000 : 0;
  return applications.filter((item) => {
    const job = trackedJob(item);
    const stage = statusFilter.value === 'all' || (statusFilter.value === 'terminal' ? item.status.is_terminal : item.status.slug === statusFilter.value);
    return `${job.title} ${job.company_name}`.toLowerCase().includes(term) && stage && (!cutoff || new Date(item.updated_at).valueOf() >= cutoff);
  });
}

function render() {
  const items = filtered();
  count.textContent = `${items.length} ${deletedToggle.checked ? 'recently deleted' : 'active'} application${items.length === 1 ? '' : 's'}`;
  if (!items.length) {
    renderEmpty(host, deletedToggle.checked ? 'Recently Deleted is empty' : 'No applications are in motion', deletedToggle.checked ? 'Deleted applications remain here for 30 days.' : 'Add a catalog job or create a private manual record.');
    return;
  }
  const roll = document.createElement('div');
  roll.className = 'film-roll live-film-roll';
  const table = document.createElement('div');
  table.className = 'film-table live-film-table';
  table.innerHTML = '<div class="film-head"><span>Job / Company</span><span>Location</span><span>Stage</span><span>Started</span><span>Updated</span><span>Notes</span><span>Actions</span></div>';
  items.forEach((item) => {
    const job = trackedJob(item);
    const row = document.createElement('article');
    row.className = 'film-row live-film-row';
    const dossier = item.job ? `/app/job-detail.html?id=${item.job.id}` : '';
    row.innerHTML = `<div class="film-cell film-role"><div class="company-lockup">${companyMark(job.company_name, job.company_logo_url)}<span><strong class="company-name">${esc(job.company_name)}</strong><span class="role-title">${esc(job.title)}</span><small>${item.manual_job ? `Private manual job · ${esc(label(job.job_family_slug))}` : 'Shared catalog job'}</small></span></div></div>
      <div class="film-cell"><small>Location</small><strong>${esc(job.location || 'Not listed')}</strong></div>
      <div class="film-cell"><select class="film-edit-control" data-stage${item.deleted_at ? ' disabled' : ''}>${statuses.map((status) => `<option value="${esc(status.slug)}"${status.slug === item.status.slug ? ' selected' : ''}>${esc(status.name)}</option>`).join('')}</select><small>Reports as ${esc(label(item.status.standard_category))}</small></div>
      <div class="film-cell"><small>Started</small><strong>${esc(absoluteDate(item.created_at))}</strong></div>
      <div class="film-cell"><small>Last movement</small><strong>${esc(relativeDate(item.updated_at))}</strong></div>
      <div class="film-cell"><small>Field note</small><strong>${esc(item.notes || 'No note yet')}</strong></div>
      <div class="film-cell action-row">${item.deleted_at ? '<button class="button" type="button" data-restore>Restore</button><button class="text-button" type="button" data-permanent>Delete permanently</button>' : '<button class="button button-dark" type="button" data-open>Open frame</button>'}${dossier ? `<a class="text-button" href="${dossier}">Job dossier</a>` : ''}</div>`;
    row.querySelector('[data-stage]')?.addEventListener('change', (event) => updateStage(item, event.currentTarget));
    row.querySelector('[data-open]')?.addEventListener('click', () => openApplication(item));
    row.querySelector('[data-restore]')?.addEventListener('click', () => restoreApplication(item));
    row.querySelector('[data-permanent]')?.addEventListener('click', () => permanentlyDelete(item));
    table.append(row);
  });
  roll.append(table);
  host.replaceChildren(roll);
}

async function updateStage(item, select) {
  setBusy(select, true);
  try { Object.assign(item, await api.updateApplication(item.id, { status: select.value, status_note: 'Stage updated from the tracker' })); makeToast(`Application moved to ${item.status.name}.`); render(); }
  catch (error) { makeToast(error.message, 'error'); await load(); }
}

function showDialog() { if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', ''); }
function closeDialog() { if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open'); }

async function openApplication(item) {
  const job = trackedJob(item);
  dialogContent.innerHTML = `<div class="dialog-head"><div><p class="utility-label">Application frame / #${item.id}</p><h2>${esc(job.title)}</h2><p>${esc(job.company_name)} · ${esc(item.status.name)} · reports as ${esc(label(item.status.standard_category))}</p></div><button class="icon-button" type="button" data-close aria-label="Close">×</button></div><div class="dialog-grid"><section><label class="field-label" for="application-notes">Application notes</label><textarea class="notes-area" id="application-notes">${esc(item.notes || '')}</textarea><label class="field-label" for="application-link">Related link</label><input class="text-input" id="application-link" type="url" value="${esc(item.link_url || '')}" placeholder="https://"><div class="action-row"><button class="button button-primary" type="button" data-save>Save notes and link</button><button class="button button-danger" type="button" data-delete>Move to Recently Deleted</button></div><hr><h3>Record an event</h3><form data-event-form><label class="field-label" for="event-type">Event type</label><select class="select-field full-field" id="event-type" name="event_type"><option value="note">Note</option><option value="follow_up">Follow up</option><option value="online_assessment">Online assessment</option><option value="interview">Interview</option><option value="recruiter_contact">Recruiter contact</option><option value="rejection">Rejection</option><option value="offer">Offer</option></select><label class="field-label" for="event-notes">Event notes</label><textarea class="text-area" id="event-notes" name="notes" required></textarea><button class="button button-dark" type="submit">Add event</button></form></section><section><p class="section-label">Timeline</p><div data-timeline></div></section></div>`;
  dialogContent.querySelector('[data-close]').addEventListener('click', closeDialog);
  dialogContent.querySelector('[data-save]').addEventListener('click', async (event) => {
    setBusy(event.currentTarget, true);
    try { Object.assign(item, await api.updateApplication(item.id, { notes: dialogContent.querySelector('#application-notes').value, link_url: dialogContent.querySelector('#application-link').value || null })); makeToast('Application details saved.'); render(); }
    catch (error) { makeToast(error.message, 'error'); }
    setBusy(event.currentTarget, false);
  });
  dialogContent.querySelector('[data-delete]').addEventListener('click', async () => {
    if (!confirm(`Move ${job.title} to Recently Deleted for 30 days?`)) return;
    await api.deleteApplication(item.id); closeDialog(); makeToast('Application moved to Recently Deleted.'); await load();
  });
  dialogContent.querySelector('[data-event-form]').addEventListener('submit', async (event) => {
    event.preventDefault();
    await api.createEvent(item.id, { event_type: event.currentTarget.elements.event_type.value, notes: event.currentTarget.elements.notes.value });
    event.currentTarget.reset(); makeToast('Timeline event recorded.'); await renderTimeline(item.id);
  });
  showDialog();
  await renderTimeline(item.id);
}

async function renderTimeline(id) {
  const target = dialogContent.querySelector('[data-timeline]');
  loading(target, 'Reading the event trail…');
  try {
    const events = await api.events(id);
    target.innerHTML = events.slice().reverse().map((event) => `<article class="timeline-event"><span class="timeline-mark"></span><div><p class="utility-label">${esc(label(event.event_type))} / ${esc(absoluteDate(event.occurred_at))}</p><h4>${esc(event.new_status ? `Moved to ${label(event.new_status)}` : label(event.event_type))}</h4><p>${esc(event.notes || 'No additional note')}</p></div></article>`).join('') || '<p>No events recorded.</p>';
  } catch (error) { renderError(target, error); }
}

function openAddDialog() {
  dialogContent.innerHTML = `<div class="dialog-head"><div><p class="utility-label">New application / Shared catalog</p><h2>Add an application</h2><p>Search the catalog. Adding a second application is always an explicit action from an existing job dossier.</p></div><button class="icon-button" type="button" data-close>×</button></div><label class="search-field dialog-search"><input type="search" data-job-search placeholder="Search by title or company" aria-label="Search jobs"></label><div data-job-results class="dialog-results"></div>`;
  dialogContent.querySelector('[data-close]').addEventListener('click', closeDialog);
  dialogContent.querySelector('[data-job-search]').addEventListener('input', debounce(searchJobs, 300));
  renderEmpty(dialogContent.querySelector('[data-job-results]'), 'Search the catalog', 'Enter a title or company.');
  showDialog();
}

async function searchJobs(event) {
  const target = dialogContent.querySelector('[data-job-results]');
  const term = event.target.value.trim();
  if (!term) return;
  loading(target, 'Searching…');
  try {
    const jobs = (await api.jobs({ search: term, active: true, limit: 20 })).filter((job) => !job.has_application);
    target.innerHTML = jobs.map((job) => `<button class="job-choice" type="button" data-job="${job.id}"><span><strong>${esc(job.title)}</strong><small>${esc(job.company_name)} · ${esc(job.location || 'Location not listed')}</small></span><span class="tag">Add</span></button>`).join('');
    target.querySelectorAll('[data-job]').forEach((button) => button.addEventListener('click', async () => { setBusy(button, true); await api.createApplication(button.dataset.job); closeDialog(); makeToast('Application added.'); await load(); }));
  } catch (error) { renderError(target, error); }
}

function openManualDialog() {
  dialogContent.innerHTML = `<div class="dialog-head"><div><p class="utility-label">Private record</p><h2>Add a manual job</h2><p>This record and its application stay visible only to you.</p></div><button class="icon-button" type="button" data-close>×</button></div><form data-manual-form class="form-grid"><label class="control-field"><span>Company</span><input name="company_name" required maxlength="255"></label><label class="control-field"><span>Title</span><input name="title" required maxlength="500"></label><label class="control-field"><span>Location</span><input name="location" maxlength="500"></label><label class="control-field"><span>Job family</span><select name="job_family_slug">${['software-engineering','data-analytics','product-management','design-user-experience','finance-accounting','consulting-strategy','marketing-communications','sales-business-development','operations-supply-chain','human-resources-recruiting','legal-compliance','research','other'].map((family) => `<option value="${family}">${esc(label(family))}</option>`).join('')}</select></label><label class="control-field"><span>Posting link</span><input name="posting_url" type="url"></label><label class="control-field"><span>Application notes</span><textarea name="application_notes"></textarea></label><button class="button button-primary" type="submit">Create private application</button></form>`;
  dialogContent.querySelector('[data-close]').addEventListener('click', closeDialog);
  dialogContent.querySelector('[data-manual-form]').addEventListener('submit', async (event) => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); setBusy(button, true);
    try { await api.createManualJob({ company_name: form.elements.company_name.value, title: form.elements.title.value, location: form.elements.location.value || null, job_family_slug: form.elements.job_family_slug.value, posting_url: form.elements.posting_url.value || null, application_notes: form.elements.application_notes.value || null }); closeDialog(); makeToast('Private manual job and application created.'); await load(); }
    catch (error) { makeToast(error.message, 'error'); setBusy(button, false); }
  });
  showDialog();
}

async function restoreApplication(item) { await api.restoreApplication(item.id); makeToast('Application restored.'); await load(); }
async function permanentlyDelete(item) { const job = trackedJob(item); if (!confirm(`Permanently delete ${job.title}? This cannot be undone.`)) return; await api.permanentlyDeleteApplication(item.id); makeToast('Application permanently deleted.'); await load(); }

async function load() {
  loading(host, deletedToggle.checked ? 'Opening Recently Deleted…' : 'Developing the application film roll…');
  try {
    [applications, statuses] = await Promise.all([api.applications({ recently_deleted: deletedToggle.checked }), api.statuses()]);
    statusFilter.replaceChildren(new Option('All stages', 'all'), new Option('Terminal stages', 'terminal'));
    statuses.forEach((status) => statusFilter.append(new Option(`${status.name} (${label(status.standard_category)})`, status.slug)));
    render();
  } catch (error) { renderError(host, error, load); }
}

document.querySelector('[data-add]').addEventListener('click', openAddDialog);
document.querySelector('[data-manual]').addEventListener('click', openManualDialog);
deletedToggle.addEventListener('change', load);
search.addEventListener('input', debounce(render, 180));
statusFilter.addEventListener('change', render);
dateFilter.addEventListener('change', render);
dialog.addEventListener('click', (event) => { if (event.target === dialog) closeDialog(); });
load();
