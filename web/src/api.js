/**
 * API client for Pocketwatcher Config API
 */

const API_BASE = '/api';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ============== Triggers ==============

export async function getTriggers() {
  return request('/triggers');
}

export async function updateTriggers(triggers) {
  return request('/triggers', {
    method: 'PUT',
    body: JSON.stringify({ triggers }),
  });
}

export async function validateTriggers(triggers) {
  return request('/triggers/validate', {
    method: 'POST',
    body: JSON.stringify({ triggers }),
  });
}

export async function resetTriggers() {
  return request('/triggers/reset', {
    method: 'POST',
  });
}

// ============== Settings ==============

export async function getSettings() {
  return request('/settings');
}

export async function updateSettings(settings) {
  return request('/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

export async function updateAlertSettings(settings) {
  return request('/settings/alerts', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

export async function updateBackpressureSettings(settings) {
  return request('/settings/backpressure', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

export async function updateDetectionSettings(settings) {
  return request('/settings/detection', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

// ============== Stats ==============

export async function getStats() {
  return request('/stats');
}

export async function getAlerts(limit = 50, offset = 0, mint = null) {
  let path = `/alerts?limit=${limit}&offset=${offset}`;
  if (mint) {
    path += `&mint=${mint}`;
  }
  return request(path);
}

export async function getHealth() {
  return request('/health');
}

export async function getHotTokens() {
  return request('/hot-tokens');
}

export async function getTokenStats(mint) {
  return request(`/token/${mint}/stats`);
}
