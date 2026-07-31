import {
  getAuthState,
  sendMagicLink,
  signInWithGoogle,
  signInWithPassword,
} from '../auth.js?v=20260729-1';
import '../navigation.js?v=20260729-1';

const status = document.querySelector('[data-auth-status]');
const params = new URLSearchParams(location.search);

function nextPath() {
  const candidate = params.get('next');
  return candidate?.startsWith('/app/') ? candidate : '/app/dashboard.html';
}

function show(message, kind = 'info') {
  status.hidden = false;
  status.dataset.kind = kind;
  status.textContent = message;
}

function busy(form, value) {
  form.querySelectorAll('button, input').forEach((control) => {
    control.disabled = value;
  });
}

async function start() {
  const auth = await getAuthState();
  if (auth.session && auth.profile) {
    location.replace(nextPath());
    return;
  }
  if (!auth.configured) {
    show('Authentication is not configured on this server. Add the public Supabase settings to continue.', 'error');
    return;
  }
  const reason = params.get('reason');
  if (reason === 'expired') show('Your session expired. Sign in again to continue.');
  if (reason === 'required') show('Sign in to open that route.');
  if (reason === 'denied' || auth.profileError) {
    show(auth.profileError?.message || 'This identity does not have an active Hunt Board invitation.', 'error');
  }
  if (reason === 'signed-out') show('Signed out. Your private job-search data is no longer available in this browser.');
}

document.querySelector('[data-google]').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await signInWithGoogle();
  } catch (error) {
    show(error.message, 'error');
    button.disabled = false;
  }
});

document.querySelector('[data-password-form]').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = new FormData(form);
  busy(form, true);
  try {
    await signInWithPassword(fields.get('email'), fields.get('password'));
    location.replace(nextPath());
  } catch (error) {
    show(error.message, 'error');
    busy(form, false);
  }
});

document.querySelector('[data-link-form]').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = new FormData(form);
  busy(form, true);
  try {
    await sendMagicLink(fields.get('email'));
    show('Check your inbox. The sign-in link returns to this field desk.');
    form.reset();
  } catch (error) {
    show(error.message, 'error');
  } finally {
    busy(form, false);
  }
});

void start();
