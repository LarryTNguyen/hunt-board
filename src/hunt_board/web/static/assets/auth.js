const PUBLIC_PATHS = new Set([
  '/app/',
  '/app/index.html',
  '/app/sign-in.html',
  '/app/job-discovery.html',
  '/app/job-detail.html',
]);
const ADMIN_PATHS = new Set(['/app/operations.html', '/app/duplicate-review.html']);

const authState = {
  ready: null,
  client: null,
  session: null,
  profile: null,
  configured: false,
};

function signInUrl(reason = '') {
  const target = `${location.pathname}${location.search}`;
  const params = new URLSearchParams({ next: target });
  if (reason) params.set('reason', reason);
  return `/app/sign-in.html?${params}`;
}

async function loadSupabase(config) {
  const module = await import('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm');
  return module.createClient(config.supabase_url, config.supabase_anon_key, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      flowType: 'pkce',
    },
  });
}

async function resolveProfile(session) {
  const response = await fetch('/auth/activate', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${session.access_token}`,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.detail || 'This account cannot enter Hunt Board.');
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function bootstrap() {
  const configResponse = await fetch('/auth/config', { headers: { Accept: 'application/json' } });
  if (!configResponse.ok) throw new Error('Authentication configuration is unavailable.');
  const config = await configResponse.json();
  authState.configured = config.enabled;
  if (!config.enabled) return authState;

  authState.client = await loadSupabase(config);
  const { data, error } = await authState.client.auth.getSession();
  if (error) throw error;
  authState.session = data.session;
  if (authState.session) {
    try {
      authState.profile = await resolveProfile(authState.session);
    } catch (error) {
      if (error.status === 403 || error.status === 401) {
        await authState.client.auth.signOut({ scope: 'local' });
        authState.session = null;
      }
      authState.profileError = error;
    }
  }
  authState.client.auth.onAuthStateChange((_event, session) => {
    authState.session = session;
    if (!session) authState.profile = null;
  });
  return authState;
}

export function initializeAuth() {
  if (!authState.ready) authState.ready = bootstrap();
  return authState.ready;
}

export async function getAuthState() {
  await initializeAuth();
  return authState;
}

export async function authenticatedFetch(path, options = {}) {
  await initializeAuth();
  const headers = { ...(options.headers || {}) };
  if (authState.session?.access_token) {
    headers.Authorization = `Bearer ${authState.session.access_token}`;
  }
  let response = await fetch(path, { ...options, headers });
  if (response.status === 401 && authState.client && authState.session) {
    const { data } = await authState.client.auth.refreshSession();
    authState.session = data.session;
    if (authState.session?.access_token) {
      headers.Authorization = `Bearer ${authState.session.access_token}`;
      response = await fetch(path, { ...options, headers });
    }
  }
  if (response.status === 401 && !PUBLIC_PATHS.has(location.pathname)) {
    location.assign(signInUrl('expired'));
  }
  return response;
}

export async function guardCurrentPage() {
  await initializeAuth();
  if (!PUBLIC_PATHS.has(location.pathname) && !authState.session) {
    location.replace(signInUrl(authState.profileError ? 'denied' : 'required'));
    return false;
  }
  if (ADMIN_PATHS.has(location.pathname) && authState.profile?.role !== 'admin') {
    location.replace('/app/dashboard.html?reason=admin-required');
    return false;
  }
  document.documentElement.dataset.session = authState.session ? 'authenticated' : 'anonymous';
  return true;
}

export async function signOut() {
  await initializeAuth();
  if (authState.client) await authState.client.auth.signOut();
  authState.session = null;
  authState.profile = null;
  location.assign('/app/sign-in.html?reason=signed-out');
}

export async function signInWithPassword(email, password) {
  await initializeAuth();
  if (!authState.client) throw new Error('Supabase authentication is not configured.');
  const result = await authState.client.auth.signInWithPassword({ email, password });
  if (result.error) throw result.error;
  authState.session = result.data.session;
  authState.profile = await resolveProfile(result.data.session);
  return authState.profile;
}

export async function signInWithGoogle() {
  await initializeAuth();
  if (!authState.client) throw new Error('Supabase authentication is not configured.');
  const result = await authState.client.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: `${location.origin}/app/sign-in.html` },
  });
  if (result.error) throw result.error;
}

export async function sendMagicLink(email) {
  await initializeAuth();
  if (!authState.client) throw new Error('Supabase authentication is not configured.');
  const result = await authState.client.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${location.origin}/app/sign-in.html` },
  });
  if (result.error) throw result.error;
}

void guardCurrentPage();
