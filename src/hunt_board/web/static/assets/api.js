export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function request(path, options = {}) {
  const init = { ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } };
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
  }
  let response;
  try {
    response = await authenticatedFetch(path, init);
  } catch (error) {
    throw new ApiError('Hunt Board could not reach the server. Check that the API is running.', 0, error.message);
  }
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof data === 'object' ? data.detail : data;
    const readable = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
      : (typeof detail === 'string' ? detail : JSON.stringify(detail || data));
    throw new ApiError(`Request failed (${response.status}): ${readable || response.statusText}`, response.status, detail);
  }
  return data;
}

export const api = {
  jobs: (params = {}) => request(`/jobs?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  publicJobs: (params = {}) => request(`/public/jobs?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  discoveryFeed: (params = {}) => request(`/jobs/feed?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  job: (id) => request(`/jobs/${id}`),
  markJobSeen: (id) => request(`/jobs/${id}/seen`, { method: 'POST', body: {} }),
  saveJob: (id, notes) => request(`/jobs/${id}/save`, { method: 'POST', body: notes === undefined ? {} : { notes } }),
  unsaveJob: (id) => request(`/jobs/${id}/save`, { method: 'DELETE' }),
  updateSaved: (id, notes) => request(`/saved-jobs/${id}`, { method: 'PATCH', body: { notes } }),
  savedJobs: (params = {}) => request(`/saved-jobs?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  discardJob: (id) => request(`/jobs/${id}/discard`, { method: 'POST', body: {} }),
  restoreJob: (id) => request(`/jobs/${id}/discard`, { method: 'DELETE' }),
  discardedJobs: () => request('/discarded-jobs?limit=200'),
  statuses: () => request('/application-statuses'),
  applications: (params = {}) => request(`/applications?${new URLSearchParams({ limit: 200, ...params })}`),
  application: (id) => request(`/applications/${id}`),
  createApplication: (id, body = {}) => request(`/jobs/${id}/applications`, { method: 'POST', body }),
  updateApplication: (id, body) => request(`/applications/${id}`, { method: 'PATCH', body }),
  deleteApplication: (id) => request(`/applications/${id}`, { method: 'DELETE' }),
  restoreApplication: (id) => request(`/applications/${id}/restore`, { method: 'POST', body: {} }),
  permanentlyDeleteApplication: (id) => request(`/applications/${id}/permanent`, { method: 'DELETE' }),
  createManualJob: (body) => request('/manual-jobs', { method: 'POST', body }),
  createStatus: (body) => request('/application-statuses', { method: 'POST', body }),
  events: (id) => request(`/applications/${id}/events`),
  createEvent: (id, body) => request(`/applications/${id}/events`, { method: 'POST', body }),
  notifications: (unread) => request(`/notifications${unread === undefined ? '' : `?unread=${unread}`}`),
  readNotification: (id) => request(`/notifications/${id}/read`, { method: 'PATCH', body: {} }),
  readAllNotifications: () => request('/notifications/read-all', { method: 'POST', body: {} }),
  preferences: () => request('/me/preferences'),
  updatePreferences: (body) => request('/me/preferences', { method: 'PATCH', body }),
  rescore: () => request('/me/preferences/rescore', { method: 'POST', body: {} }),
  onboarding: () => request('/me/preferences/onboarding'),
  updateOnboarding: (action) => request('/me/preferences/onboarding', { method: 'POST', body: { action } }),
  duplicates: (status = 'open') => request(`/admin/duplicates?status=${encodeURIComponent(status)}`),
  updateDuplicate: (id, body) => request(`/admin/duplicates/${id}`, { method: 'PATCH', body }),
  operations: () => request('/admin/operations'),
  scrapeRunSources: (id) => request(`/admin/scrape-runs/${id}/sources`),
  runDueSources: (dryRun = false) => request('/admin/ingestion/run', { method: 'POST', body: { dry_run: dryRun } }),
  runSource: (id, dryRun = false) => request(`/admin/ingestion/run-source/${id}?dry_run=${dryRun}`, { method: 'POST', body: {} }),
  syncSources: () => request('/admin/sources/sync-from-yaml', { method: 'POST', body: {} }),
  invitations: () => request('/admin/invitations'),
  createInvitation: (email) => request('/admin/invitations', { method: 'POST', body: { email } }),
  revokeInvitation: (id) => request(`/admin/invitations/${id}/revoke`, { method: 'POST', body: {} }),
  savedSearches: (params = {}) => request(`/saved-searches?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  savedSearch: (id) => request(`/saved-searches/${id}`),
  createSavedSearch: (body) => request('/saved-searches', { method: 'POST', body }),
  updateSavedSearch: (id, body) => request(`/saved-searches/${id}`, { method: 'PATCH', body }),
  deleteSavedSearch: (id) => request(`/saved-searches/${id}`, { method: 'DELETE' }),
  savedSearchMatches: (id, params = {}) => request(`/saved-searches/${id}/matches?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  markSavedSearchReviewed: (id) => request(`/saved-searches/${id}/mark-reviewed`, { method: 'POST', body: {} }),
  dailyDashboard: () => request('/dashboard/daily'),
};
import { authenticatedFetch } from './auth.js?v=20260729-1';
