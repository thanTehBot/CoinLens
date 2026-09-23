const test = require('node:test');
const assert = require('node:assert/strict');
const { isAdminUser, mapSupabaseUser, friendlyAuthError } = require('../authLogic');

test('recognizes admin users only by role', () => {
  assert.equal(isAdminUser({ role: 'admin' }), true);
  assert.equal(isAdminUser({ role: 'Admin' }), true);
  assert.equal(isAdminUser({ role: 'member' }), false);
  assert.equal(isAdminUser({ email: 'admin@coinlens.app' }), false);
  assert.equal(isAdminUser(null), false);
});

test('mapSupabaseUser returns null for no user', () => {
  assert.equal(mapSupabaseUser(null), null);
  assert.equal(mapSupabaseUser(undefined), null);
});

test('mapSupabaseUser pulls name/role from user_metadata', () => {
  const mapped = mapSupabaseUser({
    id: 'abc-123',
    email: 'jane@example.com',
    created_at: '2024-01-01T00:00:00.000Z',
    user_metadata: { name: 'Jane', role: 'admin' },
  });
  assert.equal(mapped.id, 'abc-123');
  assert.equal(mapped.name, 'Jane');
  assert.equal(mapped.email, 'jane@example.com');
  assert.equal(mapped.role, 'admin');
  assert.equal(mapped.createdAt, Date.parse('2024-01-01T00:00:00.000Z'));
});

test('mapSupabaseUser defaults role to member and name to email', () => {
  const mapped = mapSupabaseUser({ id: 'x', email: 'guest@example.com', user_metadata: {} });
  assert.equal(mapped.role, 'member');
  assert.equal(mapped.name, 'guest@example.com');
});

test('friendlyAuthError maps known Supabase messages', () => {
  assert.equal(
    friendlyAuthError({ message: 'User already registered' }),
    'An account with this email already exists.'
  );
  assert.equal(
    friendlyAuthError({ message: 'Invalid login credentials' }),
    'Incorrect email or password.'
  );
});

test('friendlyAuthError falls back to the raw message', () => {
  assert.equal(friendlyAuthError({ message: 'Some other error' }), 'Some other error');
  assert.equal(friendlyAuthError({}), 'Something went wrong. Please try again.');
});
