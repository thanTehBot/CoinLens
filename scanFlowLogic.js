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

module.exports = {
  getCaptureStageMeta,
};
