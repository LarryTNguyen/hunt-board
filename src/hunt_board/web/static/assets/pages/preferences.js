import '../navigation.js?v=20260731-1';
import { api } from '../api.js?v=20260731-1';
import { escapeHtml as esc, label } from '../format.js?v=20260721-2';
import { loading, makeToast, renderError, setBusy } from '../ui.js?v=20260721-1';

const host = document.querySelector('[data-preferences]');
const families = [
  'software-engineering', 'data-analytics', 'product-management', 'design-user-experience',
  'finance-accounting', 'consulting-strategy', 'marketing-communications',
  'sales-business-development', 'operations-supply-chain', 'human-resources-recruiting',
  'legal-compliance', 'research', 'other',
];
const levels = ['internship', 'co-op', 'new-grad', 'entry-level', 'experienced'];
const employmentTypes = ['internship', 'co-op', 'contract', 'part-time', 'full-time'];
const workplaces = ['remote', 'hybrid', 'on-site'];
let preferences;
let onboarding;

function choices(name, values, selected = [], className = 'choice-grid') {
  return `<div class="${className}">${values.map((value) => `<label class="choice"><input type="checkbox" name="${name}" value="${esc(value)}"${selected.includes(value) ? ' checked' : ''}> ${esc(label(value))}</label>`).join('')}</div>`;
}

function textLines(name, title, values, example) {
  return `<label class="field-label" for="${name}">${title}</label><textarea class="text-area" id="${name}" name="${name}" rows="4" placeholder="${esc(example)}">${esc((values || []).join('\n'))}</textarea>`;
}

function render() {
  const reminder = onboarding.state === 'completed' ? '' : `<section class="preference-reminder"><div><span class="utility-label">Optional setup</span><strong>${onboarding.state === 'skipped' ? 'Your broad All Jobs feed is ready.' : 'You can start broad or tune the route now.'}</strong><p>Preferences improve ordering, but the catalog remains usable without them.</p></div><div class="action-row"><button class="button button-quiet" type="button" data-skip>Skip for now</button><button class="button" type="button" data-complete>Mark setup complete</button></div></section>`;
  host.innerHTML = `${reminder}<form class="settings-layout" data-form><nav class="settings-index" aria-label="Preference sections"><a href="#families">Families</a><a href="#titles">Titles and terms</a><a href="#work">Work shape</a><a href="#territory">Territory</a><a href="#compensation">Compensation</a></nav><div class="settings-form">
    <section class="kit-section" id="families"><header class="kit-head"><div><p class="utility-label">Specimen tray / Primary route</p><h2>Job families</h2></div><span class="tag">Choose any number</span></header><div class="kit-body"><p class="field-note">These fixed families make discovery portable across every ATS. Related families are used only as the final transparent relaxation step.</p><span class="field-label">Selected families</span>${choices('selected_job_families', families, preferences.selected_job_families, 'family-specimen-grid')}<span class="field-label">Related families allowed during relaxation</span>${choices('related_job_families', families, preferences.related_job_families, 'family-specimen-grid')}</div></section>
    <section class="kit-section" id="titles"><header class="kit-head"><div><p class="utility-label">Kit 02 / Language</p><h2>Titles and terms</h2></div><span class="tag">Exact exclusions stay fixed</span></header><div class="kit-body">${textLines('desired_titles', 'Desired titles', preferences.desired_titles, 'Financial analyst\nProduct designer')}${textLines('include_keywords', 'Required keywords', preferences.include_keywords, 'forecasting\nconsumer research')}${textLines('exclude_keywords', 'Excluded keywords', preferences.exclude_keywords, 'principal\ncommission only')}${textLines('excluded_companies', 'Excluded companies', preferences.excluded_companies, 'Company name')}</div></section>
    <section class="kit-section" id="work"><header class="kit-head"><div><p class="utility-label">Kit 03 / Work shape</p><h2>Level and employment</h2></div></header><div class="kit-body"><span class="field-label">Experience levels</span>${choices('preferred_levels', levels, preferences.preferred_levels)}<span class="field-label">Employment types</span>${choices('employment_types', employmentTypes, preferences.employment_types)}<span class="field-label">Workplace preferences</span>${choices('workplace_preferences', workplaces, preferences.workplace_preferences)}<label class="control-field sponsorship-field"><span>Sponsorship requirement</span><select name="sponsorship_required"><option value="">No requirement</option><option value="true"${preferences.sponsorship_required === true ? ' selected' : ''}>Sponsorship must be available</option><option value="false"${preferences.sponsorship_required === false ? ' selected' : ''}>Sponsorship not required</option></select></label></div></section>
    <section class="kit-section" id="territory"><header class="kit-head"><div><p class="utility-label">Kit 04 / Territory</p><h2>Locations and countries</h2></div></header><div class="kit-body">${textLines('preferred_locations', 'Preferred cities or regions', preferences.preferred_locations, 'Seattle\nNew York')}${textLines('preferred_countries', 'Included countries', preferences.preferred_countries, 'US\nCanada')}${textLines('excluded_countries', 'Excluded countries', preferences.excluded_countries, 'Country code or name')}<div class="form-grid"><label><span class="field-label">Home location</span><input class="text-input" name="home_location" value="${esc(preferences.home_location || '')}" placeholder="Optional"></label><label><span class="field-label">Radius in miles</span><input class="text-input" name="radius_miles" type="number" min="0" max="500" value="${preferences.radius_miles || 0}"></label><label><span class="field-label">Country context</span><input class="text-input" name="country" value="${esc(preferences.country || '')}" placeholder="Optional"></label><label class="choice choice-single"><input type="checkbox" name="remote_allowed"${preferences.remote_allowed ? ' checked' : ''}> Remote roles are allowed</label></div></div></section>
    <section class="kit-section" id="compensation"><header class="kit-head"><div><p class="utility-label">Kit 05 / Ordering</p><h2>Compensation and score</h2></div><output class="threshold-output" for="minimum-score" data-threshold>${preferences.minimum_score_threshold}</output></header><div class="kit-body"><div class="form-grid"><label><span class="field-label">Minimum annual salary</span><input class="text-input" name="minimum_salary" type="number" min="0" step="1000" value="${preferences.minimum_salary ?? ''}" placeholder="Optional"></label><label><span class="field-label">Minimum route score</span><input class="range-input" id="minimum-score" name="minimum_score_threshold" type="range" min="0" max="100" step="1" value="${preferences.minimum_score_threshold}"></label></div><p>Jobs without salary data stay visible below confirmed matches. Salary is the first filter the relaxed feed may broaden.</p></div></section>
    <div class="sticky-actions"><p class="form-status" data-status aria-live="polite"></p><button class="button button-primary" type="submit">Save and update feed</button></div>
  </div></form>`;
  const form = host.querySelector('[data-form]');
  form.addEventListener('submit', save);
  form.elements.minimum_score_threshold.addEventListener('input', () => { form.querySelector('[data-threshold]').textContent = form.elements.minimum_score_threshold.value; });
  host.querySelector('[data-skip]')?.addEventListener('click', () => setOnboarding('skip'));
  host.querySelector('[data-complete]')?.addEventListener('click', () => setOnboarding('complete'));
}

function lines(value) { return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean); }
function checked(form, name) { return [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value); }

async function setOnboarding(action) {
  try { onboarding = await api.updateOnboarding(action); render(); makeToast(action === 'skip' ? 'Setup skipped. Showing a broad feed.' : 'Preference setup marked complete.'); }
  catch (error) { makeToast(error.message, 'error'); }
}

async function save(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const status = form.querySelector('[data-status]');
  setBusy(button, true);
  status.textContent = 'Saving and recalculating the visible route…';
  const sponsor = form.elements.sponsorship_required.value;
  const body = {
    selected_job_families: checked(form, 'selected_job_families'), related_job_families: checked(form, 'related_job_families'),
    desired_titles: lines(form.elements.desired_titles.value), include_keywords: lines(form.elements.include_keywords.value), exclude_keywords: lines(form.elements.exclude_keywords.value), excluded_companies: lines(form.elements.excluded_companies.value),
    preferred_levels: checked(form, 'preferred_levels'), employment_types: checked(form, 'employment_types'), workplace_preferences: checked(form, 'workplace_preferences'),
    preferred_locations: lines(form.elements.preferred_locations.value), preferred_countries: lines(form.elements.preferred_countries.value), excluded_countries: lines(form.elements.excluded_countries.value),
    radius_miles: Number(form.elements.radius_miles.value || 0), remote_allowed: form.elements.remote_allowed.checked,
    sponsorship_required: sponsor === '' ? null : sponsor === 'true', minimum_salary: form.elements.minimum_salary.value === '' ? null : Number(form.elements.minimum_salary.value), minimum_score_threshold: Number(form.elements.minimum_score_threshold.value),
  };
  if (form.elements.home_location.value.trim()) body.home_location = form.elements.home_location.value.trim();
  if (form.elements.country.value.trim()) body.country = form.elements.country.value.trim();
  try {
    preferences = await api.updatePreferences(body);
    onboarding = await api.updateOnboarding('complete');
    status.textContent = 'Preferences saved. Visible results now use this route.';
    makeToast('Preferences saved and feed updated.');
    render();
  } catch (error) { status.textContent = error.message; makeToast(error.message, 'error'); }
  setBusy(button, false);
}

async function load() {
  loading(host, 'Unpacking your field kit…');
  try { [preferences, onboarding] = await Promise.all([api.preferences(), api.onboarding()]); render(); }
  catch (error) { renderError(host, error, load); }
}
load();
