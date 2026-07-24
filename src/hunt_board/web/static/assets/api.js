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
    response = await fetch(path, init);
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
  discoveryFeed: (params = {}) => request(`/jobs/feed?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null))}`),
  job: (id) => request(`/jobs/${id}`),
  saveJob: (id, notes) => request(`/jobs/${id}/save`, { method: 'POST', body: notes === undefined ? {} : { notes } }),
  unsaveJob: (id) => request(`/jobs/${id}/save`, { method: 'DELETE' }),
  updateSaved: (id, notes) => request(`/saved-jobs/${id}`, { method: 'PATCH', body: { notes } }),
  savedJobs: () => request('/saved-jobs?limit=200'),
  discardJob: (id) => request(`/jobs/${id}/discard`, { method: 'POST', body: {} }),
  restoreJob: (id) => request(`/jobs/${id}/discard`, { method: 'DELETE' }),
  discardedJobs: () => request('/discarded-jobs?limit=200'),
  statuses: () => request('/application-statuses'),
  applications: () => request('/applications?limit=200'),
  application: (id) => request(`/applications/${id}`),
  createApplication: (id, body = {}) => request(`/jobs/${id}/applications`, { method: 'POST', body }),
  updateApplication: (id, body) => request(`/applications/${id}`, { method: 'PATCH', body }),
  deleteApplication: (id) => request(`/applications/${id}`, { method: 'DELETE' }),
  events: (id) => request(`/applications/${id}/events`),
  createEvent: (id, body) => request(`/applications/${id}/events`, { method: 'POST', body }),
  notifications: (unread) => request(`/notifications${unread === undefined ? '' : `?unread=${unread}`}`),
  readNotification: (id) => request(`/notifications/${id}/read`, { method: 'PATCH', body: {} }),
  readAllNotifications: () => request('/notifications/read-all', { method: 'POST', body: {} }),
  preferences: () => request('/me/preferences'),
  updatePreferences: (body) => request('/me/preferences', { method: 'PATCH', body }),
  rescore: () => request('/me/preferences/rescore', { method: 'POST', body: {} }),
  duplicates: (status = 'open') => request(`/admin/duplicates?status=${encodeURIComponent(status)}`),
  updateDuplicate: (id, body) => request(`/admin/duplicates/${id}`, { method: 'PATCH', body }),
  ingestionHealth: () => request('/health/ingestion'),
  operations: () => request('/admin/operations'),
  scrapeRunSources: (id) => request(`/admin/scrape-runs/${id}/sources`),
  runDueSources: (dryRun = false) => request('/admin/ingestion/run', { method: 'POST', body: { dry_run: dryRun } }),
  runSource: (id, dryRun = false) => request(`/admin/ingestion/run-source/${id}?dry_run=${dryRun}`, { method: 'POST', body: {} }),
  syncSources: () => request('/admin/sources/sync-from-yaml', { method: 'POST', body: {} }),
};
