function getCaptureStageMeta(stage) {
  if (stage === 'back') {
    return {
      title: 'Flip the Coin',
      body: 'Flip the coin over, center the back of the coin in the frame, and tap the button below to capture.',
    };
  }

  return {
    title: 'Front of the Coin',
    body: 'Center the front of the coin in the frame and tap the button below to capture.',
  };
}

// Image state for one scan, kept outside React state so the exact images
// submitted to /api/identify-coin never depend on a render closure. Each
// scan gets its own scanId; a response whose scanId is no longer current
// belongs to an abandoned scan and must not be shown as this scan's result.
function createScanImages(scanId = 0) {
  return { scanId, front: null, back: null };
}

// Capturing (or retaking) the front starts the pair over - a back image
// taken against a previous front must never be submitted with a new one.
function recordCapture(images, stage, image) {
  if (!image) throw new Error('No image data was captured.');
  if (stage === 'front') return { ...images, front: image, back: null };
  if (stage === 'back') {
    if (!images.front) throw new Error('The front photo is missing.');
    return { ...images, back: image };
  }
  throw new Error(`Unknown capture stage: ${stage}`);
}

function retakeStage(images, stage) {
  if (stage === 'front') return { ...images, front: null, back: null };
  if (stage === 'back') return { ...images, back: null };
  throw new Error(`Unknown capture stage: ${stage}`);
}

// Returns the exact identifyCoin(front, back, source) arguments for the
// current images, or null when the scan isn't complete for that source.
function buildIdentifyArgs(images, source) {
  if (source === 'camera') {
    return images.front && images.back ? [images.front, images.back, 'camera'] : null;
  }
  if (source === 'gallery') {
    return images.front ? [images.front, null, 'gallery'] : null;
  }
  return null;
}

function isCurrentScan(activeScanId, scanId) {
  return activeScanId === scanId;
}

module.exports = {
  getCaptureStageMeta,
  createScanImages,
  recordCapture,
  retakeStage,
  buildIdentifyArgs,
  isCurrentScan,
};
