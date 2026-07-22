import '../navigation.js?v=20260721-1';
import { api } from '../api.js?v=20260721-1';
import { escapeHtml as esc, label } from '../format.js?v=20260721-1';
import { loading, makeToast, renderError, setBusy } from '../ui.js?v=20260721-1';

const host = document.querySelector('[data-preferences]');
const roleGroups = ['software_engineering', 'backend', 'machine_learning', 'data_science', 'full_stack', 'fullstack', 'data'];
const levels = ['intern', 'entry', 'junior', 'mid', 'senior', 'staff', 'principal', 'lead', 'manager', 'director'];
let preferences;

function choices(name, values, selected) {
  return `<div class="choice-grid">${values.map((value) => `<label class="choice"><input type="checkbox" name="${name}" value="${esc(value)}"${selected.includes(value) ? ' checked' : ''}> ${esc(label(value))}</label>`).join('')}</div>`;
}

function render() {
  host.innerHTML = `<form class="settings-layout" data-form><nav class="settings-index" aria-label="Preference sections"><a href="#titles">Title matching</a><a href="#level">Level</a><a href="#location">Territory</a><a href="#threshold">Route threshold</a></nav><div class="settings-form">
    <section class="kit-section" id="titles"><header class="kit-head"><div><p class="utility-label">Kit 01 / strict signals</p><h2>Title matching</h2></div><span class="tag">40% ranking weight</span></header><div class="kit-body"><label class="field-label" for="include-keywords">Exact include phrases</label><textarea class="text-area" id="include-keywords" name="include_keywords" rows="6">${esc(preferences.include_keywords.join('\n'))}</textarea><p>One phrase per line. Exact multi-word includes intentionally win before exclusions.</p><label class="field-label" for="exclude-keywords">Excluded title phrases</label><textarea class="text-area" id="exclude-keywords" name="exclude_keywords" rows="5">${esc(preferences.exclude_keywords.join('\n'))}</textarea><p class="field-note">Example: “Staff Backend Engineer” still qualifies when “backend engineer” is an exact include. After changing phrases, run <strong>Rescore stored jobs</strong> so earlier ingestions use the new instructions.</p><span class="field-label">Flexible role groups</span>${choices('role_groups', roleGroups, preferences.role_groups)}</div></section>
    <section class="kit-section" id="level"><header class="kit-head"><div><p class="utility-label">Kit 02 / role shape</p><h2>Preferred levels</h2></div><span class="tag">20% ranking weight</span></header><div class="kit-body">${choices('preferred_levels', levels, preferences.preferred_levels)}</div></section>
    <section class="kit-section" id="location"><header class="kit-head"><div><p class="utility-label">Kit 03 / territory</p><h2>Location and work type</h2></div><span class="tag">15% ranking weight</span></header><div class="kit-body"><label class="field-label" for="locations">Preferred locations</label><textarea class="text-area" id="locations" name="preferred_locations" rows="4">${esc(preferences.preferred_locations.join('\n'))}</textarea><p class="field-note">Preferred-location phrases drive ranking today. Country is saved as profile context, but it is not yet a strict geographic boundary because ATS location text is not normalized to countries.</p><div class="form-grid"><label><span class="field-label">Home location</span><input class="text-input" name="home_location" value="${esc(preferences.home_location)}" required></label><label><span class="field-label">Radius in miles</span><input class="text-input" name="radius_miles" type="number" min="0" max="500" value="${preferences.radius_miles}" required></label><label><span class="field-label">Country context</span><input class="text-input" name="country" value="${esc(preferences.country)}" required></label><label class="choice choice-single"><input type="checkbox" name="remote_allowed"${preferences.remote_allowed ? ' checked' : ''}> Remote roles are allowed</label></div></div></section>
    <section class="kit-section" id="threshold"><header class="kit-head"><div><p class="utility-label">Kit 04 / visible route</p><h2>Minimum score threshold</h2></div><output class="threshold-output" for="minimum-score" data-threshold>${preferences.minimum_score_threshold}</output></header><div class="kit-body"><label class="field-label" for="minimum-score">Minimum route score, 0 to 100</label><input class="range-input" id="minimum-score" name="minimum_score_threshold" type="range" min="0" max="100" step="1" value="${preferences.minimum_score_threshold}"><p>Jobs below this threshold remain stored but are counted as hidden or low-ranked after rescoring.</p></div></section>
    <div class="sticky-actions"><p class="form-status" data-status aria-live="polite"></p><button class="button" type="button" data-rescore>Rescore stored jobs</button><button class="button button-primary" type="submit">Save changes</button></div><section class="rescore-summary" data-summary hidden aria-live="polite"></section>
  </div></form>`;
  const form = host.querySelector('[data-form]');
  form.addEventListener('submit', save);
  form.querySelector('[data-rescore]').addEventListener('click', rescore);
  form.elements.minimum_score_threshold.addEventListener('input', () => { form.querySelector('[data-threshold]').textContent = form.elements.minimum_score_threshold.value; });
}

function lines(value) {
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function checked(form, name) {
  return [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

async function save(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const status = form.querySelector('[data-status]');
  setBusy(button, true);
  status.textContent = 'Saving route instructions…';
  const body = {
    include_keywords: lines(form.elements.include_keywords.value), exclude_keywords: lines(form.elements.exclude_keywords.value), role_groups: checked(form, 'role_groups'), preferred_levels: checked(form, 'preferred_levels'), preferred_locations: lines(form.elements.preferred_locations.value), home_location: form.elements.home_location.value.trim(), radius_miles: Number(form.elements.radius_miles.value), country: form.elements.country.value.trim(), remote_allowed: form.elements.remote_allowed.checked, minimum_score_threshold: Number(form.elements.minimum_score_threshold.value),
  };
  try { preferences = await api.updatePreferences(body); status.textContent = 'Preferences saved. Run a rescore to apply them to stored jobs.'; makeToast('Search-route preferences saved.'); } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); }
  setBusy(button, false);
}

async function rescore(event) {
  const button = event.currentTarget;
  const status = host.querySelector('[data-status]');
  const summary = host.querySelector('[data-summary]');
  setBusy(button, true);
  status.textContent = 'Rescoring stored sightings…';
  summary.hidden = true;
  try {
    const result = await api.rescore();
    status.textContent = 'Rescore complete.';
    summary.innerHTML = `<h2>Route recalculated</h2><dl class="rescore-grid"><div><dt>Considered</dt><dd>${result.total_jobs_considered}</dd></div><div><dt>Rescored</dt><dd>${result.total_jobs_rescored}</dd></div><div><dt>Visible</dt><dd>${result.total_visible_jobs}</dd></div><div><dt>Hidden / low</dt><dd>${result.total_hidden_or_low_ranked_jobs}</dd></div><div><dt>Duration</dt><dd>${result.duration_ms} ms</dd></div></dl>`;
    summary.hidden = false;
    makeToast('Stored jobs rescored.');
  } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); }
  setBusy(button, false);
}

async function load() {
  loading(host, 'Unpacking your field kit…');
  try { preferences = await api.preferences(); render(); } catch (error) { renderError(host, error, load); }
}
load();
