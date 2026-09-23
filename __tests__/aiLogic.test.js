const test = require('node:test');
const assert = require('node:assert/strict');
const { extractJSON, getModelCandidates, isRetryableError } = require('../aiLogic');

test('extractJSON parses a valid object wrapped in explanatory text', () => {
  const text = 'Here is the result: {"country":"United States","year":"1964"} Thanks!';
  assert.deepEqual(extractJSON(text), { country: 'United States', year: '1964' });
});

test('extractJSON handles nested arrays and objects', () => {
  const text = 'Response: {"title":"Classic coin","item_specifics":[{"label":"Grade","value":"MS-65"}],"notes":{"shipping":"Priority"}}';
  assert.deepEqual(extractJSON(text), {
    title: 'Classic coin',
    item_specifics: [{ label: 'Grade', value: 'MS-65' }],
    notes: { shipping: 'Priority' },
  });
});

test('extractJSON throws a helpful error for malformed JSON', () => {
  assert.throws(() => extractJSON('{"country": "US"'), /malformed data/i);
});

test('getModelCandidates uses a fallback for gpt-4o requests', () => {
  assert.deepEqual(getModelCandidates('gpt-4o'), ['gpt-4o', 'gpt-4o-mini']);
  assert.deepEqual(getModelCandidates('gpt-4o-mini'), ['gpt-4o-mini']);
});

test('isRetryableError returns true for model-related failures', () => {
  const retriable = {
    status: 404,
    message: 'The model gpt-4o does not exist',
  };
  assert.equal(isRetryableError(retriable), true);
  assert.equal(isRetryableError({ status: 401, message: 'Invalid API key' }), false);
  assert.equal(isRetryableError({ status: 500, message: 'Server error' }), false);
});
