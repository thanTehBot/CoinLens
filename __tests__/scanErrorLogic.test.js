const test = require('node:test');
const assert = require('node:assert/strict');
const { ScanError, makeErrorDetail } = require('../scanErrorLogic');

test('quota_exceeded is marked non-retryable and keeps the daily-limit title', () => {
  const detail = makeErrorDetail(new ScanError('quota_exceeded', 'Daily scan limit of 3 reached. Try again tomorrow.'));
  assert.equal(detail.code, 'quota_exceeded');
  assert.equal(detail.retryable, false);
  assert.equal(detail.title, 'Daily Scan Limit Reached');
  // The body is the server's message, so it carries the actual configured
  // limit dynamically instead of a hardcoded number in the UI layer.
  assert.match(detail.body, /3/);
});

test('other scan errors remain retryable', () => {
  const codes = ['network', 'server_error', 'rate_limit', 'identification_failure', 'unknown'];
  for (const code of codes) {
    const detail = makeErrorDetail(new ScanError(code, 'some message'));
    assert.equal(detail.retryable, true, `expected ${code} to remain retryable`);
  }
});

test('a plain (non-ScanError) error falls back to the retryable unknown display', () => {
  const detail = makeErrorDetail(new Error('boom'));
  assert.equal(detail.code, 'unknown');
  assert.equal(detail.retryable, true);
  assert.equal(detail.body, 'boom');
});

// -- rate_limit: OpenAI's real retry-after propagated through ScanError,
// with the action (Try Again vs Back to Home) driven by how long the wait
// actually is, instead of a hardcoded "30 seconds" regardless of reality.

test('rate_limit with a 30 second retry-after shows Try Again', () => {
  const detail = makeErrorDetail(new ScanError('rate_limit', 'AI provider rate or quota limit reached.', { retryAfterSeconds: 30 }));
  assert.equal(detail.code, 'rate_limit');
  assert.equal(detail.title, 'Rate Limit Hit');
  assert.equal(detail.retryable, true);
  assert.equal(detail.tip, 'Try again in about 30 seconds.');
});

test('rate_limit with a 5 minute (300s) retry-after shows Back to Home', () => {
  const detail = makeErrorDetail(new ScanError('rate_limit', 'AI provider rate or quota limit reached.', { retryAfterSeconds: 300 }));
  assert.equal(detail.retryable, false);
  assert.equal(detail.tip, 'Try again in about 5 minutes.');
});

test('rate_limit with an 11042s (~3 hour) retry-after shows Back to Home', () => {
  const detail = makeErrorDetail(new ScanError('rate_limit', 'AI provider rate or quota limit reached.', { retryAfterSeconds: 11042 }));
  assert.equal(detail.retryable, false);
  assert.equal(detail.tip, 'Try again in about 3 hours.');
});

test('rate_limit with no retry-after falls back to a conservative Try Again, no false 30s claim', () => {
  const detail = makeErrorDetail(new ScanError('rate_limit', 'AI provider rate or quota limit reached.'));
  assert.equal(detail.retryable, true);
  assert.equal(detail.tip, 'Wait a short time and try again.');
  assert.doesNotMatch(detail.tip, /30 seconds/);
});

test('quota_exceeded Back to Home behavior is unaffected by the rate_limit change', () => {
  const detail = makeErrorDetail(new ScanError('quota_exceeded', 'Daily scan limit of 20 reached. Try again tomorrow.'));
  assert.equal(detail.retryable, false);
  assert.equal(detail.title, 'Daily Scan Limit Reached');
});

test('another normal retryable error (network) keeps its existing Try Again behavior', () => {
  const detail = makeErrorDetail(new ScanError('network', 'No internet connection. Could not reach CoinLens.'));
  assert.equal(detail.retryable, true);
  assert.equal(detail.title, 'No Internet');
});

// -- ai_incomplete: OpenAI exhausted its reasoning budget before producing
// visible output. This must read as a temporary processing failure, never
// as "coin not recognized"/bad photo, and must stay retryable.

test('ai_incomplete shows the AI-processing-interrupted message and stays retryable', () => {
  const detail = makeErrorDetail(new ScanError('ai_incomplete', "The AI service couldn't finish processing this scan."));
  assert.equal(detail.code, 'ai_incomplete');
  assert.equal(detail.title, 'AI Processing Interrupted');
  assert.equal(detail.body, "The AI service couldn't finish processing this scan.");
  assert.equal(detail.retryable, true);
});

test('ai_incomplete never claims a lighting/image/unrecognized problem', () => {
  const detail = makeErrorDetail(new ScanError('ai_incomplete', "The AI service couldn't finish processing this scan."));
  const combinedText = `${detail.title} ${detail.body} ${detail.tip ?? ''}`.toLowerCase();
  assert.doesNotMatch(combinedText, /lighting/);
  assert.doesNotMatch(combinedText, /not recognized/);
  assert.doesNotMatch(combinedText, /bad (image|photo)/);
});

test('ai_incomplete is distinct from identification_failure', () => {
  const incomplete = makeErrorDetail(new ScanError('ai_incomplete', "The AI service couldn't finish processing this scan."));
  const unrecognized = makeErrorDetail(new ScanError('identification_failure', 'AI provider returned an empty response.'));
  assert.notEqual(incomplete.title, unrecognized.title);
});
