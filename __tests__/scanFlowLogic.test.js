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

const {
  createScanImages,
  recordCapture,
  retakeStage,
  buildIdentifyArgs,
  isCurrentScan,
} = require('../scanFlowLogic');

function completedScan(scanId, front, back) {
  let images = createScanImages(scanId);
  images = recordCapture(images, 'front', front);
  return recordCapture(images, 'back', back);
}

test('a new scan starts with no images from the previous scan', () => {
  const previous = completedScan(1, 'old-front', 'old-back');
  const next = createScanImages(previous.scanId + 1);
  assert.equal(next.front, null);
  assert.equal(next.back, null);
  assert.equal(buildIdentifyArgs(next, 'camera'), null);
  assert.equal(isCurrentScan(next.scanId, previous.scanId), false);

  const current = recordCapture(recordCapture(next, 'front', 'new-front'), 'back', 'new-back');
  assert.deepEqual(buildIdentifyArgs(current, 'camera'), ['new-front', 'new-back', 'camera']);
});

test('retaking the front replaces the submitted front and discards the old back', () => {
  let images = completedScan(1, 'front-1', 'back-1');
  images = retakeStage(images, 'front');
  assert.equal(buildIdentifyArgs(images, 'camera'), null);
  images = recordCapture(images, 'front', 'front-2');
  assert.equal(images.back, null, 'a back taken against the previous front must not survive');
  images = recordCapture(images, 'back', 'back-2');
  assert.deepEqual(buildIdentifyArgs(images, 'camera'), ['front-2', 'back-2', 'camera']);

  // Capturing the front again without an explicit retake behaves the same.
  images = recordCapture(images, 'front', 'front-3');
  assert.deepEqual([images.front, images.back], ['front-3', null]);
});

test('retaking the back replaces the submitted back and keeps the front', () => {
  let images = completedScan(1, 'front-1', 'back-1');
  images = retakeStage(images, 'back');
  assert.equal(buildIdentifyArgs(images, 'camera'), null);
  images = recordCapture(images, 'back', 'back-2');
  assert.deepEqual(buildIdentifyArgs(images, 'camera'), ['front-1', 'back-2', 'camera']);
});

test('recording captures never mutates an earlier scan state', () => {
  const first = recordCapture(createScanImages(1), 'front', 'front-1');
  const second = recordCapture(first, 'back', 'back-1');
  assert.equal(first.back, null);
  assert.notEqual(first, second);
});

test('back capture without a front and empty captures are rejected', () => {
  assert.throws(() => recordCapture(createScanImages(1), 'back', 'back-1'), /front photo is missing/);
  assert.throws(() => recordCapture(createScanImages(1), 'front', undefined), /No image data/);
  assert.throws(() => recordCapture(createScanImages(1), 'side', 'x'), /Unknown capture stage/);
});

test('gallery scans submit only the chosen photo', () => {
  const images = recordCapture(createScanImages(4), 'front', 'upload');
  assert.deepEqual(buildIdentifyArgs(images, 'gallery'), ['upload', null, 'gallery']);
  assert.equal(buildIdentifyArgs(createScanImages(5), 'gallery'), null);
});
