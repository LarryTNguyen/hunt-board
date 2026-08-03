import { decoratePageIntro } from '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { absoluteDate, activateCompanyLogos, companyMark, country, descriptionText, escapeHtml as esc, humanRankingReason, label, locationWithCountry, roleLevel, safeUrl, salary, score } from '../format.js?v=20260721-2';
import { loading, makeToast, renderError, setBusy } from '../ui.js?v=20260721-1';

const host = document.querySelector('[data-detail]');
const id = new URLSearchParams(window.location.search).get('id');
let job;

function allLocations() {
  const locations = Array.isArray(job.locations) ? job.locations.filter((item) => item?.display) : [];
  return locations.length ? locations.map((item) => item.display).join(' / ') : (job.location || 'Not listed');
}

function tags() {
  return [job.is_saved && 'Saved', job.has_application && (job.application_status?.name || 'Applied'), job.is_duplicate && 'Duplicate', job.is_reposted && 'Reposted', job.active ? 'Active' : 'Closed'].filter(Boolean);
}

function render() {
  const official = safeUrl(job.apply_url) || safeUrl(job.posting_url);
  host.innerHTML = `<header class="page-intro dossier-intro"><div><p class="coordinate">Observation dossier / Job #${job.id} / ${esc(job.source_slug)}</p><div class="action-row">${tags().map((tag) => `<span class="tag">${esc(tag)}</span>`).join('')}</div></div><a class="button" href="/app/job-discovery.html">Back to sightings</a></header>
    <div class="dossier-grid"><article class="sheet"><section class="sheet-block"><p class="utility-label">${esc(job.source?.ats || job.source_slug)} / ${esc(roleLevel(job.title))} / ${esc(label(job.workplace_type, 'Work arrangement not provided'))}</p><h1 class="sheet-title">${esc(job.title)}</h1><div class="company-lockup detail-company-lockup">${companyMark(job.company_name, job.company_logo_url)}<span><strong>${esc(job.company_name)}</strong><span>${esc(locationWithCountry(job))}</span></span></div><div class="action-row dossier-actions">${job.is_saved ? '<button class="button" data-save>Remove saved job</button>' : '<button class="button" data-save>Save job</button>'}${job.has_application ? `<a class="button button-dark" href="/app/application-tracker.html?application=${job.application_id}">Open in tracker</a>` : '<button class="button button-dark" data-track>Add to tracker</button>'}${official ? `<a class="button button-primary" href="${esc(official)}" target="_blank" rel="noopener noreferrer">Open official posting</a>` : ''}</div></section>
      <section class="sheet-block detail-copy"><p class="section-label">Description / Source text</p><div class="description-text" data-description></div></section></article>
      <aside><section class="sheet"><div class="sheet-block"><p class="section-label">Route score</p><div class="detail-score">${score(job.ranking_score)}<small>/ 100</small></div><div class="score-bar" aria-label="Match score ${score(job.ranking_score)} out of 100"><i style="--score:${Math.min(100, Math.max(0, score(job.ranking_score)))}%"></i></div></div><div class="sheet-block"><h2 class="section-label">Why it ranked</h2><ul class="reason-list reason-cards">${(job.ranking_reasons?.length ? job.ranking_reasons : ['No ranking reasons recorded']).map((reason) => `<li>${esc(humanRankingReason(reason))}</li>`).join('')}</ul></div><div class="sheet-block"><dl class="meta-list"><div><dt>Locations</dt><dd>${esc(allLocations())}</dd></div><div><dt>Country</dt><dd>${esc(country(job))}</dd></div><div><dt>Compensation</dt><dd>${esc(salary(job))}</dd></div><div><dt>Role level</dt><dd>${esc(roleLevel(job.title))}</dd></div><div><dt>Work arrangement</dt><dd>${esc(label(job.workplace_type, 'Not provided'))}</dd></div><div><dt>First seen</dt><dd>${esc(absoluteDate(job.first_seen_at))}</dd></div><div><dt>Last seen</dt><dd>${esc(absoluteDate(job.last_seen_at))}</dd></div><div><dt>Posted</dt><dd>${esc(absoluteDate(job.posted_at))}</dd></div><div><dt>Source</dt><dd>${esc(job.source?.name || job.source_slug)}</dd></div><div><dt>Department</dt><dd>${esc(job.department || 'Not listed')}</dd></div><div><dt>Employment</dt><dd>${esc(job.employment_type || 'Not listed')}</dd></div></dl></div></section>
      <section class="sheet notes-sheet"><div class="sheet-block"><label class="section-label" for="field-notes">Saved field notes</label><textarea class="notes-area" id="field-notes" placeholder="Add the context you want beside this opportunity…"></textarea><button class="button button-primary notes-save" type="button" data-notes>Save notes</button><p class="form-status" data-note-status aria-live="polite"></p></div></section></aside></div>`;
  host.querySelector('[data-description]').textContent = descriptionText(job.description_html, job.description_text) || 'No description was supplied by the ATS source.';
  activateCompanyLogos(host);
  decoratePageIntro();
  host.querySelector('[data-save]').addEventListener('click', toggleSave);
  host.querySelector('[data-track]')?.addEventListener('click', createApplication);
  host.querySelector('[data-notes]').addEventListener('click', saveNotes);
  loadNotes();
}

async function loadNotes() {
  if (!job.is_saved) return;
  try {
    const saved = (await api.savedJobs()).find((entry) => entry.id === job.saved_job_id || entry.job.id === job.id);
    if (saved) {
      job.saved_job_id = saved.id;
      host.querySelector('#field-notes').value = saved.notes || '';
    }
  } catch (error) { host.querySelector('[data-note-status]').textContent = `Notes unavailable: ${error.message}`; }
}

async function toggleSave(event) {
  setBusy(event.currentTarget, true);
  try {
    if (job.is_saved) { await api.unsaveJob(job.id); job.is_saved = false; job.saved_job_id = null; makeToast('Job removed from the field board.'); }
    else { const saved = await api.saveJob(job.id); job.is_saved = true; job.saved_job_id = saved.id; makeToast('Job saved to the field board.'); }
    render();
  } catch (error) { makeToast(error.message, 'error'); setBusy(event.currentTarget, false); }
}

async function saveNotes(event) {
  const button = event.currentTarget;
  const notes = host.querySelector('#field-notes').value;
  const status = host.querySelector('[data-note-status]');
  setBusy(button, true);
  status.textContent = 'Saving notes…';
  try {
    if (!job.is_saved) {
      const saved = await api.saveJob(job.id, notes);
      job.is_saved = true;
      job.saved_job_id = saved.id;
    } else await api.updateSaved(job.saved_job_id, notes);
    status.textContent = 'Notes saved.';
    makeToast('Field notes saved.');
    setBusy(button, false);
  } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); setBusy(button, false); }
}

async function createApplication(event) {
  setBusy(event.currentTarget, true);
  try {
    const application = await api.createApplication(job.id);
    job.has_application = true;
    job.application_id = application.id;
    job.application_status = application.status;
    makeToast('Application added to the tracker.');
    render();
  } catch (error) { makeToast(error.message, 'error'); setBusy(event.currentTarget, false); }
}

async function load() {
  loading(host, 'Opening the observation dossier…');
  if (!id || !/^\d+$/.test(id)) {
    renderError(host, new Error('Choose a job from discovery before opening its dossier.'));
    return;
  }
  try { job = await api.markJobSeen(id); render(); } catch (error) { renderError(host, error, load); }
}
load();
