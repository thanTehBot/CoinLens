const test = require('node:test');
const assert = require('node:assert/strict');
const { BADGES, BADGE_CATEGORIES } = require('../src/badges/badges.js');

// Badge ELIGIBILITY is decided authoritatively by server/badges.py (see
// server/tests/test_badges.py) via GET /api/badges/me and GET /api/leaderboard.
// This file only owns display metadata, so these tests just guard that
// metadata's shape and its lockstep with the server's badge ids.

test('every badge has the display fields the UI needs, and no eligibility check function', () => {
  for (const badge of BADGES) {
    assert.equal(typeof badge.id, 'string');
    assert.equal(typeof badge.icon, 'string');
    assert.equal(typeof badge.name, 'string');
    assert.equal(typeof badge.desc, 'string');
    assert.ok(BADGE_CATEGORIES.includes(badge.category), `${badge.id} has an unknown category`);
    assert.equal(badge.check, undefined, `${badge.id} should not carry client-side eligibility logic`);
  }
});

test('badge ids are unique', () => {
  const ids = BADGES.map(b => b.id);
  assert.equal(ids.length, new Set(ids).size);
});

test('every category in BADGE_CATEGORIES has at least one badge', () => {
  for (const cat of BADGE_CATEGORIES) {
    assert.ok(BADGES.some(b => b.category === cat), `no badge found for category ${cat}`);
  }
});
