function normalizeRole(role) {
  return String(role || '').trim().toLowerCase();
}

function isAdminUser(user) {
  if (!user) return false;
  return normalizeRole(user.role) === 'admin';
}

function mapSupabaseUser(supabaseUser) {
  if (!supabaseUser) return null;
  const metadata = supabaseUser.user_metadata || {};
  return {
    id: supabaseUser.id,
    name: metadata.display_name || metadata.name || supabaseUser.email || 'Member',
    email: supabaseUser.email || '',
    role: normalizeRole(metadata.role) === 'admin' ? 'admin' : 'member',
    createdAt: supabaseUser.created_at ? new Date(supabaseUser.created_at).getTime() : Date.now(),
  };
}

const FRIENDLY_AUTH_ERRORS = [
  [/already registered/i, 'An account with this email already exists.'],
  [/invalid login credentials/i, 'Incorrect email or password.'],
  [/password should be at least/i, 'Password must be at least 6 characters.'],
];

function friendlyAuthError(error) {
  const message = error?.message || 'Something went wrong. Please try again.';
  const match = FRIENDLY_AUTH_ERRORS.find(([pattern]) => pattern.test(message));
  return match ? match[1] : message;
}

module.exports = {
  isAdminUser,
  mapSupabaseUser,
  friendlyAuthError,
};
