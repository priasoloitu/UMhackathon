/**
 * restrictions.js — Restrictions panel logic.
 * Handles day blocks, time blocks, custom rules via /api/restrictions.
 */
const Restrictions = (() => {
  let restrictions = [];

  // ── API helpers ────────────────────────────────────────────────────────────

  async function _fetchAll() {
    const res = await fetch('/api/restrictions', { credentials: 'include' });
    if (res.ok) restrictions = await res.json();
    else restrictions = [];
  }

  async function _add(payload) {
    const res = await fetch('/api/restrictions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('Failed to save restriction');
    const r = await res.json();
    restrictions.push(r);
    return r;
  }

  async function _delete(id) {
    await fetch(`/api/restrictions/${id}`, { method: 'DELETE', credentials: 'include' });
    restrictions = restrictions.filter(r => r.id !== id);
  }

  // ── Render restriction list ────────────────────────────────────────────────

  function _renderList() {
    const ul = document.getElementById('restrictions-list');
    if (!ul) return;

    if (restrictions.length === 0) {
      ul.innerHTML = '<li class="restrictions-empty">No restrictions set yet.</li>';
      return;
    }

    ul.innerHTML = '';
    restrictions.forEach(r => {
      const li = document.createElement('li');
      li.className = 'restriction-item';

      const info = document.createElement('div');
      info.innerHTML = `
        <div class="restriction-item__type">${r.type.replace('_', ' ')}</div>
        <div class="restriction-item__value">${_escHtml(r.label || r.value)}</div>
      `;

      const del = document.createElement('button');
      del.className   = 'restriction-item__delete';
      del.textContent = '✕';
      del.title       = 'Remove restriction';
      del.addEventListener('click', async () => {
        await _delete(r.id);
        _renderList();
        _syncDayCheckboxes();
      });

      li.appendChild(info);
      li.appendChild(del);
      ul.appendChild(li);
    });
  }

  // ── Sync day checkboxes to current restrictions ────────────────────────────

  function _syncDayCheckboxes() {
    const blockedDays = restrictions
      .filter(r => r.type === 'day_block')
      .map(r => r.value.toLowerCase());

    document.querySelectorAll('#day-block-grid input[type="checkbox"]').forEach(cb => {
      cb.checked = blockedDays.includes(cb.value.toLowerCase());
    });
  }

  // ── Open / close ───────────────────────────────────────────────────────────

  async function open() {
    await _fetchAll();
    _renderList();
    _syncDayCheckboxes();
    const overlay = document.getElementById('restrictions-overlay');
    if (overlay) overlay.style.display = 'flex';
  }

  function close() {
    const overlay = document.getElementById('restrictions-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    // Settings button
    document.getElementById('settings-btn')?.addEventListener('click', open);

    // Close button
    document.getElementById('restrictions-close')?.addEventListener('click', close);

    // Close on overlay click
    document.getElementById('restrictions-overlay')?.addEventListener('click', e => {
      if (e.target === e.currentTarget) close();
    });

    // Day block checkboxes
    document.querySelectorAll('#day-block-grid input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', async e => {
        const day = cb.value;
        if (e.target.checked) {
          try {
            await _add({ type: 'day_block', value: day, label: `Block ${day}s` });
          } catch (_) { cb.checked = false; }
        } else {
          const existing = restrictions.find(r => r.type === 'day_block' && r.value === day);
          if (existing) await _delete(existing.id);
        }
        _renderList();
      });
    });

    // Time block add button
    document.getElementById('add-time-block-btn')?.addEventListener('click', async () => {
      const start = document.getElementById('time-block-start')?.value;
      const end   = document.getElementById('time-block-end')?.value;
      if (!start || !end) { alert('Please pick both start and end times.'); return; }
      if (start >= end)   { alert('End time must be after start time.'); return; }

      try {
        await _add({
          type:  'time_block',
          value: `${start}-${end}`,
          label: `No appointments ${start}–${end}`,
        });
        document.getElementById('time-block-start').value = '';
        document.getElementById('time-block-end').value   = '';
        _renderList();
      } catch(err) { alert(err.message); }
    });

    // Custom rule add button
    document.getElementById('add-custom-rule-btn')?.addEventListener('click', async () => {
      const input = document.getElementById('custom-rule-input');
      const text  = input?.value.trim();
      if (!text) { alert('Please enter a rule.'); return; }

      try {
        await _add({ type: 'custom', value: text, label: text });
        input.value = '';
        _renderList();
      } catch(err) { alert(err.message); }
    });
  }

  function _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  return { init, open, close };
})();
