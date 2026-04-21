/**
 * auth.js — API wrapper for authentication.
 * Loaded on BOTH login.html and index.html.
 */
const Auth = (() => {
  const API = '';  // same-origin

  async function _post(url, body) {
    const res = await fetch(API + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Request failed');
    return data;
  }

  async function _get(url) {
    const res = await fetch(API + url, { credentials: 'include' });
    if (!res.ok) return null;
    return res.json();
  }

  return {
    register: (username, email, password) =>
      _post('/api/auth/register', { username, email, password }),

    login: (username, password) =>
      _post('/api/auth/login', { username, password }),

    logout: () => _post('/api/auth/logout', {}),

    me: () => _get('/api/auth/me'),
  };
})();
