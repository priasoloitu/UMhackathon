/**
 * calendar.js — Renders a weekly calendar grid with task cards.
 *
 * Features:
 *  - Mon–Sun columns, 06:00–23:00 rows
 *  - Green/Amber/Red task cards based on status
 *  - Click empty slot → pre-fill chat
 *  - Click task card → pre-fill chat
 *  - Week navigation (prev / next)
 */
const Calendar = (() => {
  const START_HOUR = 6;   // 06:00
  const END_HOUR   = 23;  // 23:00
  const SLOT_H     = 52;  // px per hour

  let currentWeekOffset = 0;  // 0 = this week, -1 = last week, +1 = next week
  let tasks = [];

  // ── Helpers ────────────────────────────────────────────────────────────────

  function getMondayOf(date) {
    const d = new Date(date);
    const day = d.getDay();             // 0=Sun … 6=Sat
    const diff = (day === 0) ? -6 : 1 - day;
    d.setDate(d.getDate() + diff);
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function getWeekDates(offset = 0) {
    const monday = getMondayOf(new Date());
    monday.setDate(monday.getDate() + offset * 7);
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(monday);
      d.setDate(d.getDate() + i);
      return d;
    });
  }

  function formatDate(d) {
    return d.toISOString().slice(0, 10); // YYYY-MM-DD
  }

  function formatTimeLabel(h) {
    if (h === 0)  return '12 AM';
    if (h === 12) return '12 PM';
    return h < 12 ? `${h} AM` : `${h - 12} PM`;
  }

  function timeToMinutes(t) {
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
  }

  // ── Fetch tasks ────────────────────────────────────────────────────────────

  async function loadTasks() {
    try {
      const res = await fetch('/api/schedule', { credentials: 'include' });
      if (res.ok) tasks = await res.json();
    } catch (_) {
      tasks = [];
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  function render() {
    const container = document.getElementById('calendar-container');
    if (!container) return;

    const weekDates = getWeekDates(currentWeekOffset);
    const todayStr  = formatDate(new Date());

    // Update week label
    const start = weekDates[0];
    const end   = weekDates[6];
    const fmt   = d => d.toLocaleDateString('en-MY', { month: 'short', day: 'numeric' });
    const lbl   = document.getElementById('week-label');
    if (lbl) lbl.textContent = `${fmt(start)} – ${fmt(end)}`;

    // Build grid
    const grid = document.createElement('div');
    grid.className = 'calendar-grid';

    // ── Header row ────────────────────────────────────────────────────────────
    const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

    // time gutter header
    const gutterHead = document.createElement('div');
    gutterHead.className = 'cal-day-header time-gutter';
    grid.appendChild(gutterHead);

    weekDates.forEach((d, i) => {
      const cell = document.createElement('div');
      cell.className = 'cal-day-header' + (formatDate(d) === todayStr ? ' today' : '');

      const nameEl = document.createElement('div');
      nameEl.className = 'cal-day-name';
      nameEl.textContent = DAY_NAMES[i];

      const dateEl = document.createElement('div');
      dateEl.className = 'cal-day-date';
      dateEl.textContent = d.getDate();

      cell.appendChild(nameEl);
      cell.appendChild(dateEl);
      grid.appendChild(cell);
    });

    // ── Body rows (one per hour) ───────────────────────────────────────────────
    for (let h = START_HOUR; h < END_HOUR; h++) {
      // Time label
      const timeCell = document.createElement('div');
      timeCell.className = 'cal-time-label';
      timeCell.textContent = formatTimeLabel(h);
      grid.appendChild(timeCell);

      // Day columns
      weekDates.forEach(d => {
        const dateStr = formatDate(d);
        const timeStr = `${String(h).padStart(2, '0')}:00`;

        const slot = document.createElement('div');
        slot.className = 'cal-slot';
        slot.dataset.date = dateStr;
        slot.dataset.time = timeStr;

        slot.addEventListener('click', () => {
          if (typeof Chat !== 'undefined') {
            const dayName = d.toLocaleDateString('en-MY', { weekday: 'long' });
            Chat.prefill(`Schedule something on ${dayName}, ${fmt(d)} at ${formatTimeLabel(h)}`);
          }
        });

        grid.appendChild(slot);
      });
    }

    container.innerHTML = '';
    container.appendChild(grid);

    // ── Place task cards ───────────────────────────────────────────────────────
    tasks.forEach(task => {
      placeTaskCard(task, weekDates, grid);
    });
  }

  function placeTaskCard(task, weekDates, grid) {
    const taskDateStr = task.date;
    const colIdx = weekDates.findIndex(d => formatDate(d) === taskDateStr);
    if (colIdx === -1) return; // not in this week

    const startMins = timeToMinutes(task.start_time);
    const endMins   = task.end_time ? timeToMinutes(task.end_time) : startMins + 60;

    const startHour = startMins / 60;
    const endHour   = endMins   / 60;

    if (startHour >= END_HOUR || endHour <= START_HOUR) return;

    // find the slot cell for the start hour
    const rowIdx     = Math.max(0, Math.floor(startHour) - START_HOUR);
    // grid columns: col 0 = gutter, col 1..7 = days
    const gridColIdx = colIdx + 2; // 1-indexed CSS grid col
    const gridRowIdx = rowIdx + 2; // 1-indexed CSS grid row (row 1 = header)

    // Get all day slots for this column at the right row
    const allSlots = grid.querySelectorAll('.cal-slot');
    const daySlots = Array.from(allSlots).filter(
      s => s.dataset.date === task.date
    );
    const targetSlot = daySlots[rowIdx];
    if (!targetSlot) return;

    const card = document.createElement('div');

    // Determine if the task is in the past
    const todayMidnight = new Date(); todayMidnight.setHours(0,0,0,0);
    const taskDate      = new Date(task.date + 'T00:00:00');
    const isPast        = taskDate < todayMidnight;

    card.className = isPast
      ? 'task-card task-card--past'
      : `task-card task-card--${task.status || 'confirmed'}`;

    // Position within the slot
    const offsetMins = startMins - (Math.floor(startHour) * 60);
    const topOffset  = (offsetMins / 60) * SLOT_H;
    const height     = Math.max(24, ((endMins - startMins) / 60) * SLOT_H - 4);

    card.style.top    = `${topOffset}px`;
    card.style.height = `${height}px`;

    const titleEl = document.createElement('div');
    titleEl.className   = 'task-card__title';
    titleEl.textContent = task.title;

    const timeEl = document.createElement('div');
    timeEl.className   = 'task-card__time';
    timeEl.textContent = `${task.start_time}${task.end_time ? '–' + task.end_time : ''}`;

    card.appendChild(titleEl);
    card.appendChild(timeEl);

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.className = 'task-card__delete';
    delBtn.textContent = '✕';
    delBtn.title = 'Delete task';
    delBtn.addEventListener('click', async e => {
      e.stopPropagation();
      if (confirm(`Delete task "${task.title}"?`)) {
        try {
          const res = await fetch(`/api/schedule/${task.id}`, { method: 'DELETE', credentials: 'include' });
          if (res.ok) {
            refresh();
            if (typeof Impact !== 'undefined') Impact.refresh();
          } else {
            alert('Failed to delete task.');
          }
        } catch (err) {
          alert('Network error while deleting.');
        }
      }
    });
    card.appendChild(delBtn);

    card.addEventListener('click', e => {
      e.stopPropagation();
      _openTaskModal(task);
    });

    targetSlot.appendChild(card);
  }

  // ── Task Details Modal ─────────────────────────────────────────────────────

  let _activeTaskId = null; // track which task the modal is showing

  function _openTaskModal(task) {
    _activeTaskId = task.id;

    // Status dot colour
    const dot = document.getElementById('task-details-status-dot');
    if (dot) {
      dot.className = 'task-details-status-dot';
      if (task.status === 'warning') dot.classList.add('warning');
      else if (task.status === 'blocked') dot.classList.add('blocked');
    }

    // Title
    const title = document.getElementById('task-details-title');
    if (title) title.textContent = task.title;

    // Meta chips
    const chips = document.getElementById('task-details-chips');
    if (chips) {
      const datefmt = task.date
        ? new Date(task.date + 'T00:00:00').toLocaleDateString('en-MY', { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' })
        : task.date;
      const timeStr = task.start_time + (task.end_time ? ' – ' + task.end_time : '');
      const statusLabel = (task.status || 'confirmed').charAt(0).toUpperCase() + (task.status || 'confirmed').slice(1);
      const statusColour = task.status === 'warning' ? 'var(--amber)' : task.status === 'blocked' ? 'var(--red)' : 'var(--green)';

      chips.innerHTML = `
        <div class="detail-chip"><span class="detail-chip__icon">🗓</span>${datefmt}</div>
        <div class="detail-chip"><span class="detail-chip__icon">⏰</span>${timeStr}</div>
        ${task.location ? `<div class="detail-chip"><span class="detail-chip__icon">📍</span>${_escHtml(task.location)}</div>` : ''}
        <div class="detail-chip"><span style="width:8px;height:8px;border-radius:50%;background:${statusColour};display:inline-block;"></span>${statusLabel}</div>
      `;
    }

    // Rationale
    const rationaleEl = document.getElementById('task-details-rationale');
    if (rationaleEl) {
      let html = task.notes || '<em style="color:var(--text-muted)">No AI advice saved for this event.</em>';
      // basic markdown bold
      html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      // line breaks
      html = html.replace(/\n/g, '<br/>');
      rationaleEl.innerHTML = html;
    }

    // Show modal
    document.getElementById('task-details-overlay').style.display = 'flex';
  }

  function _closeTaskModal() {
    document.getElementById('task-details-overlay').style.display = 'none';
    _activeTaskId = null;
  }

  async function _deleteActive() {
    if (!_activeTaskId) return;
    if (!confirm('Delete this event from your calendar?')) return;
    try {
      const res = await fetch(`/api/schedule/${_activeTaskId}`, { method: 'DELETE', credentials: 'include' });
      if (res.ok) {
        _closeTaskModal();
        await refresh();
        if (typeof Impact !== 'undefined') Impact.refresh();
      } else {
        alert('Failed to delete event.');
      }
    } catch {
      alert('Network error while deleting.');
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  async function init() {
    await loadTasks();
    render();

    // Modal close triggers
    document.getElementById('task-details-close')?.addEventListener('click', _closeTaskModal);
    document.getElementById('task-details-close-btn')?.addEventListener('click', _closeTaskModal);
    document.getElementById('task-details-overlay')?.addEventListener('click', e => {
      if (e.target === e.currentTarget) _closeTaskModal();
    });

    // Delete button inside modal
    document.getElementById('task-details-delete-btn')?.addEventListener('click', _deleteActive);

    // Escape key
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') _closeTaskModal();
    });

    // Week navigation
    document.getElementById('week-prev')?.addEventListener('click', () => {
      currentWeekOffset--;
      render();
    });
    document.getElementById('week-next')?.addEventListener('click', () => {
      currentWeekOffset++;
      render();
    });
  }

  async function refresh() {
    await loadTasks();
    render();
  }

  function addTask(task) {
    tasks.push(task);
    render();
  }

  return { init, refresh, addTask };
})();
