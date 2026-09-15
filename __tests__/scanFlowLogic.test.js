const test = require('node:test');
const assert = require('node:assert/strict');
const { getCaptureStageMeta } = require('../scanFlowLogic');

test('getCaptureStageMeta returns the front prompt by default', () => {
  const meta = getCaptureStageMeta('front');
  assert.equal(meta.title, 'Front of the Coin');
  assert.match(meta.body, /front/i);
  assert.match(meta.body, /tap the button/i);
  assert.doesNotMatch(meta.body, /automatically/i);
  assert.equal(meta.autoCaptureDelayMs, undefined);
});

test('getCaptureStageMeta returns the flip prompt for the reverse side', () => {
  const meta = getCaptureStageMeta('back');
  assert.equal(meta.title, 'Flip the Coin');
  assert.match(meta.body, /back/i);
  assert.match(meta.body, /tap the button/i);
  assert.doesNotMatch(meta.body, /automatically/i);
  assert.equal(meta.autoCaptureDelayMs, undefined);
});
