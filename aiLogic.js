function findMatchingDelimiter(text, openIndex) {
  const opening = text[openIndex];
  const closing = opening === '{' ? '}' : ']';
  let depth = 0;
  let inString = false;
  let escapeNext = false;

  for (let i = openIndex; i < text.length; i += 1) {
    const char = text[i];

    if (escapeNext) {
      escapeNext = false;
      continue;
    }

    if (char === '\\') {
      escapeNext = true;
      continue;
    }

    if (char === '"') {
      inString = !inString;
      continue;
    }

    if (inString) continue;

    if (char === opening) {
      depth += 1;
    } else if (char === closing) {
      depth -= 1;
      if (depth === 0) return i;
    }
  }

  return -1;
}

function extractJSON(text) {
  if (typeof text !== 'string') {
    throw new Error('The AI did not return recognizable data. Try scanning again.');
  }

  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error('The AI did not return recognizable data. Try scanning again.');
  }

  const candidates = [trimmed.indexOf('{'), trimmed.indexOf('[')].filter((index) => index >= 0);
  const start = candidates.length > 0 ? Math.min(...candidates) : -1;

  if (start < 0) {
    throw new Error('The AI did not return recognizable data. Try scanning again.');
  }

  const end = findMatchingDelimiter(trimmed, start);
  if (end < 0) {
    throw new Error('The AI returned malformed data. Try scanning again.');
  }

  const candidate = trimmed.slice(start, end + 1);
  try {
    return JSON.parse(candidate);
  } catch {
    throw new Error('The AI returned malformed data. Try scanning again.');
  }
}

function getModelCandidates(primaryModel) {
  if (!primaryModel) return ['gpt-4o-mini'];
  if (primaryModel === 'gpt-4o') return ['gpt-4o', 'gpt-4o-mini'];
  return [primaryModel];
}

function isRetryableError(error) {
  const status = error?.status ?? error?.response?.status;
  const message = `${error?.message ?? ''} ${error?.error?.message ?? ''}`.toLowerCase();

  if (status === 404 || status === 400 || status === 403 || status === 429) return true;
  return /model|does not exist|unsupported|not found/i.test(message);
}

module.exports = {
  extractJSON,
  getModelCandidates,
  isRetryableError,
};
