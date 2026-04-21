/**
 * chat.js — Chat sidebar logic.
 *
 * Features:
 *  - Send messages → /api/chat
 *  - Render bot/user/warning/clarification/suggestion bubbles
 *  - Suggestion bubble has "Confirm & Add" button
 *  - localStorage persistence with optional clear
 *  - Ctrl+K focuses input
 *  - Typing indicator
 */
const Chat = (() => {
  const STORAGE_KEY = 'jadualiq_chat_history_v1';
  const HISTORY_LIMIT = 20; // messages kept for GLM context

  let conversationHistory = [];   // [{role, content}, ...]
  let uiMessages          = [];   // rendered bubbles, saved to localStorage
  let pendingSuggestion   = null; // the last GLM suggestion awaiting confirm

  // ── Internal helpers ───────────────────────────────────────────────────────

  function _fmt(d = new Date()) {
    return d.toLocaleTimeString('en-MY', { hour: '2-digit', minute: '2-digit' });
  }

  function _now() { return _fmt(new Date()); }

  function _scrollToBottom() {
    const el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
  }

  function _setTyping(show) {
    const el = document.getElementById('chat-typing');
    if (el) el.style.display = show ? 'flex' : 'none';
    _scrollToBottom();
  }

  function _setInputDisabled(disabled) {
    const input = document.getElementById('chat-input');
    const btn   = document.getElementById('chat-send');
    if (input) input.disabled = disabled;
    if (btn)   btn.disabled   = disabled;
  }

  // ── Persistence ────────────────────────────────────────────────────────────

  function _saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ uiMessages, conversationHistory }));
    } catch (_) {}
  }

  function _loadFromStorage() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function clearHistory() {
    uiMessages = [];
    conversationHistory = [];
    localStorage.removeItem(STORAGE_KEY);
    const container = document.getElementById('chat-messages');
    if (container) container.innerHTML = '';
    _appendGreeting();
  }

  // ── Render functions ───────────────────────────────────────────────────────

  function _createMsgEl(role, bubbleHTML, type = '') {
    const msg = document.createElement('div');
    msg.className = `chat-msg chat-msg--${role}${type ? ' chat-msg--' + type : ''}`;

    const bubble = document.createElement('div');
    bubble.className = 'chat-msg__bubble';
    bubble.innerHTML = bubbleHTML;

    const time = document.createElement('div');
    time.className   = 'chat-msg__time';
    time.textContent = _now();

    msg.appendChild(bubble);
    msg.appendChild(time);
    return msg;
  }

  function _appendToDOM(el) {
    const container = document.getElementById('chat-messages');
    if (container) {
      container.appendChild(el);
      _scrollToBottom();
    }
  }

  function appendUserMessage(text) {
    const el = _createMsgEl('user', _escHtml(text));
    _appendToDOM(el);
    uiMessages.push({ role: 'user', text });
    conversationHistory.push({ role: 'user', content: text });
    if (conversationHistory.length > HISTORY_LIMIT * 2) {
      conversationHistory = conversationHistory.slice(-HISTORY_LIMIT * 2);
    }
    _saveToStorage();
  }

  function appendBotMessage(text) {
    const el = _createMsgEl('bot', _escHtml(text).replace(/\n/g, '<br/>'));
    _appendToDOM(el);
    uiMessages.push({ role: 'bot', text });
    conversationHistory.push({ role: 'assistant', content: text });
    _saveToStorage();
  }

  function appendWarning(text) {
    const el = _createMsgEl('bot', `<div class="chat-msg__icon">⚠️</div>${_escHtml(text).replace(/\n/g, '<br/>')}`, 'warning');
    _appendToDOM(el);
    uiMessages.push({ role: 'warning', text });
    _saveToStorage();
  }

  function appendClarification(text) {
    const el = _createMsgEl('bot', `🤔 ${_escHtml(text)}`, 'clarification');
    _appendToDOM(el);
    uiMessages.push({ role: 'clarification', text });
    conversationHistory.push({ role: 'assistant', content: text });
    _saveToStorage();
  }

  function appendSuggestion(result) {
    const { parsed, explanation } = _extractParsed(result);
    if (!parsed) {
      appendBotMessage(result.glm_raw || 'Something went wrong.');
      return;
    }

    const s = parsed.suggestion;
    const weatherIcon = result.weather?.suitable_outdoor ? '☀️' : '🌧️';
    const trafficIcon = result.traffic?.peak_hour_warning ? '🚦' : '🟢';

    const html = `
      <div class="suggestion-header">
        <span class="suggestion-badge">📅 Suggestion</span>
        ${weatherIcon} ${trafficIcon}
      </div>
      <div class="suggestion-title">${_escHtml(s.title)}</div>
      <div class="suggestion-meta">
        <span>📅 ${s.date}</span>
        <span>🕐 ${s.start_time}${s.end_time ? ' – ' + s.end_time : ''}</span>
        ${s.location ? `<span>📍 ${_escHtml(s.location)}</span>` : ''}
      </div>
      <div class="suggestion-explanation">${_escHtml(explanation)}</div>
      <div class="suggestion-actions">
        <button class="sug-btn sug-btn--confirm" data-action="confirm">✅ Add to Calendar</button>
        <button class="sug-btn sug-btn--dismiss" data-action="dismiss">✕ Dismiss</button>
      </div>
    `;

    const el = _createMsgEl('bot', html, 'suggestion');
    _appendToDOM(el);

    // Wire buttons
    el.querySelector('[data-action="confirm"]').addEventListener('click', () => {
      _confirmSuggestion(s, el);
    });
    el.querySelector('[data-action="dismiss"]').addEventListener('click', () => {
      _dismissSuggestion(el);
    });

    pendingSuggestion = s;
    uiMessages.push({ role: 'suggestion', text: JSON.stringify(s) });
    conversationHistory.push({ role: 'assistant', content: explanation });
    _saveToStorage();
  }

  async function _confirmSuggestion(s, el) {
    // Disable buttons
    el.querySelectorAll('.sug-btn').forEach(b => b.disabled = true);

    try {
      const res = await fetch('/api/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(s),
      });
      if (!res.ok) throw new Error('Failed to save');
      const task = await res.json();

      // Update bubble to show confirmed
      el.querySelector('.suggestion-actions').innerHTML =
        '<span style="color:var(--green);font-size:13px;font-weight:600;">✅ Added to calendar!</span>';

      // Re-render calendar
      if (typeof Calendar !== 'undefined') await Calendar.refresh();
      if (typeof Impact   !== 'undefined') await Impact.refresh();

    } catch (err) {
      el.querySelector('.suggestion-actions').innerHTML =
        `<span style="color:var(--red);font-size:12px;">❌ ${err.message}</span>`;
    }
    pendingSuggestion = null;
  }

  function _dismissSuggestion(el) {
    el.querySelector('.suggestion-actions').innerHTML =
      '<span style="color:var(--text-muted);font-size:12px;">Dismissed.</span>';
    pendingSuggestion = null;
  }

  // ── Restore messages from localStorage ────────────────────────────────────

  function _restoreMessages() {
    const saved = _loadFromStorage();
    if (!saved || !saved.uiMessages || saved.uiMessages.length === 0) {
      _appendGreeting();
      return;
    }

    uiMessages          = saved.uiMessages;
    conversationHistory = (saved.conversationHistory || []).slice(-HISTORY_LIMIT * 2);

    // Re-render plain messages (skip suggestion bubbles — they'd need re-wiring)
    saved.uiMessages.forEach(m => {
      if (m.role === 'user')          { const el = _createMsgEl('user', _escHtml(m.text)); _appendToDOM(el); }
      if (m.role === 'bot')           { const el = _createMsgEl('bot', _escHtml(m.text).replace(/\n/g,'<br/>')); _appendToDOM(el); }
      if (m.role === 'warning')       { const el = _createMsgEl('bot', `<div class="chat-msg__icon">⚠️</div>${_escHtml(m.text).replace(/\n/g,'<br/>')}`, 'warning'); _appendToDOM(el); }
      if (m.role === 'clarification') { const el = _createMsgEl('bot', `🤔 ${_escHtml(m.text)}`, 'clarification'); _appendToDOM(el); }
      if (m.role === 'suggestion')    {
        try {
          const s = JSON.parse(m.text);
          const el = _createMsgEl('bot',
            `<div style="color:var(--text-muted);font-size:12px;">📅 Previous suggestion: <b>${_escHtml(s.title)}</b> on ${s.date} at ${s.start_time} (already handled)</div>`
          );
          _appendToDOM(el);
        } catch(_) {}
      }
    });

    if (uiMessages.length > 0) {
      appendBotMessage('Welcome back! 👋 I remember our last conversation. How can I help you schedule today?');
    }
  }

  function _appendGreeting() {
    const el = _createMsgEl('bot',
      `Hello! I'm <b>JadualIQ</b> 👋<br/><br/>
       I'm your AI scheduling assistant. Tell me what you need to schedule and I'll find the best time slot for you — considering weather, traffic, and your personal restrictions.<br/><br/>
       Try: <i>"Schedule a meeting on Wednesday at 3pm"</i>`,
    );
    _appendToDOM(el);
  }

  // ── Main send ──────────────────────────────────────────────────────────────

  async function send(message) {
    if (!message.trim()) return;

    appendUserMessage(message);
    _setInputDisabled(true);
    _setTyping(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          message,
          history: conversationHistory.slice(-HISTORY_LIMIT * 2),
        }),
      });

      const data = await res.json();
      _setTyping(false);

      if (!res.ok) {
        appendWarning(data.error || 'Something went wrong.');
        return;
      }

      // Route by response type
      if (data.type === 'warning') {
        appendWarning(data.message);
      } else if (data.type === 'clarification') {
        appendClarification(data.message);
      } else if (data.type === 'suggestion') {
        appendSuggestion(data);
      } else {
        appendBotMessage(data.message || JSON.stringify(data));
      }

    } catch (err) {
      _setTyping(false);
      appendWarning('Network error — please check your connection.');
    } finally {
      _setInputDisabled(false);
      document.getElementById('chat-input')?.focus();
    }
  }

  // ── Prefill ────────────────────────────────────────────────────────────────

  function prefill(text) {
    const input = document.getElementById('chat-input');
    if (input) {
      input.value = text;
      input.focus();
    }
  }

  // ── Misc helpers ───────────────────────────────────────────────────────────

  function _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _extractParsed(result) {
    if (!result.parsed) return { parsed: null, explanation: '' };
    const parsed      = result.parsed;
    const explanation = parsed.explanation || '';
    return { parsed, explanation };
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    _restoreMessages();

    // Form submit
    const form  = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');

    form?.addEventListener('submit', e => {
      e.preventDefault();
      const msg = input.value.trim();
      if (!msg) return;
      input.value = '';
      send(msg);
    });

    // Ctrl+K shortcut
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        input?.focus();
      }
    });

    // Clear history button
    document.getElementById('clear-history-btn')?.addEventListener('click', () => {
      if (confirm('Clear all chat history?')) {
        clearHistory();
        document.getElementById('user-badge')?.classList.remove('open');
      }
    });
  }

  return { init, send, prefill, clearHistory, appendBotMessage };
})();
