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
  const START_HOUR = 0;   // 12:00 AM (midnight)
  const END_HOUR = 24;    // 12:00 AM next day (full 24h)
  const SLOT_H = 52;      // px per hour

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
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function formatTimeLabel(h) {
    if (h === 0 || h === 24) return '12 AM';
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
      const res = await fetch('/api/schedule?_=' + Date.now(), { credentials: 'include' });
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
    const todayStr = formatDate(new Date());

    // Update week label
    const start = weekDates[0];
    const end = weekDates[6];
    const fmt = d => d.toLocaleDateString('en-MY', { month: 'short', day: 'numeric' });
    const lbl = document.getElementById('week-label');
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

      // We'll append the conflict badge here later if needed
      const badgeContainer = document.createElement('div');
      badgeContainer.id = `conflict-badge-${formatDate(d)}`;
      cell.appendChild(badgeContainer);

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

    // ── Client-side Conflict Detection ─────────────────────────────────────────
    _detectConflictsAndDrawBadges(weekDates);

    // ── Current Time Indicator ───────────────────────────────────────────────
    _drawNowLine(grid, weekDates);
  }

  function _drawNowLine(grid, weekDates) {
    // Remove existing
    grid.querySelectorAll('.cal-now-line').forEach(el => el.remove());

    const now = new Date();
    const todayStr = formatDate(now);
    const colIdx = weekDates.findIndex(d => formatDate(d) === todayStr);
    
    if (colIdx === -1) return null; // Today not in this week

    const hour = now.getHours();
    const min = now.getMinutes();

    if (hour < START_HOUR || hour >= END_HOUR) return null; // Out of visible bounds

    // The current hour slot
    const rowIdx = hour - START_HOUR;
    const allSlots = grid.querySelectorAll('.cal-slot');
    const daySlots = Array.from(allSlots).filter(s => s.dataset.date === todayStr);
    const targetSlot = daySlots[rowIdx];

    if (!targetSlot) return null;

    const line = document.createElement('div');
    line.className = 'cal-now-line';
    line.style.top = `${(min / 60) * SLOT_H}px`;
    
    targetSlot.appendChild(line);
    
    return line;
  }

  function _detectConflictsAndDrawBadges(weekDates) {
    // Group tasks by date
    const byDate = {};
    tasks.forEach(t => {
      if (!byDate[t.date]) byDate[t.date] = [];
      byDate[t.date].push(t);
    });

    weekDates.forEach(d => {
      const dateStr = formatDate(d);
      const dayTasks = byDate[dateStr] || [];
      let conflictPairs = [];

      // O(N^2) check, N is small per day
      for (let i = 0; i < dayTasks.length; i++) {
        for (let j = i + 1; j < dayTasks.length; j++) {
          const t1 = dayTasks[i];
          const t2 = dayTasks[j];
          const s1 = timeToMinutes(t1.start_time);
          const e1 = t1.end_time ? timeToMinutes(t1.end_time) : s1 + 60;
          const s2 = timeToMinutes(t2.start_time);
          const e2 = t2.end_time ? timeToMinutes(t2.end_time) : s2 + 60;

          if (s1 < e2 && e1 > s2) {
            conflictPairs.push([t1, t2]);
          }
        }
      }

      const container = document.getElementById(`conflict-badge-${dateStr}`);
      if (!container) return;
      container.innerHTML = '';

      if (conflictPairs.length > 0) {
        const badge = document.createElement('div');
        badge.className = 'conflict-badge';
        badge.textContent = `🔴 ${conflictPairs.length} conflict${conflictPairs.length > 1 ? 's' : ''}`;
        badge.title = 'Click to resolve schedule conflicts';
        badge.addEventListener('click', (e) => {
          e.stopPropagation();
          _openConflictModal(conflictPairs[0][0], conflictPairs[0][1]);
        });
        container.appendChild(badge);
      }
    });
    // Refresh the sidebar schedule list
    _renderScheduleList();
  }

  function placeTaskCard(task, weekDates, grid) {
    const taskDateStr = task.date;
    const colIdx = weekDates.findIndex(d => formatDate(d) === taskDateStr);
    if (colIdx === -1) return; // not in this week

    const startMins = timeToMinutes(task.start_time);
    const endMins = task.end_time ? timeToMinutes(task.end_time) : startMins + 60;

    const startHour = startMins / 60;
    const endHour = endMins / 60;

    if (startHour >= END_HOUR || endHour <= START_HOUR) return;

    // find the slot cell for the start hour
    const rowIdx = Math.max(0, Math.floor(startHour) - START_HOUR);
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
    const todayMidnight = new Date(); todayMidnight.setHours(0, 0, 0, 0);
    const taskDate = new Date(task.date + 'T00:00:00');
    const isPast = taskDate < todayMidnight;

    card.className = isPast
      ? 'task-card task-card--past'
      : `task-card task-card--${task.status || 'confirmed'}`;

    // Position within the slot
    const offsetMins = startMins - (Math.floor(startHour) * 60);
    const topOffset = (offsetMins / 60) * SLOT_H;
    const height = Math.max(24, ((endMins - startMins) / 60) * SLOT_H - 4);

    card.style.top = `${topOffset}px`;
    card.style.height = `${height}px`;

    const titleEl = document.createElement('div');
    titleEl.className = 'task-card__title';
    titleEl.textContent = task.title;

    const timeEl = document.createElement('div');
    timeEl.className = 'task-card__time';
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
      // Two-click confirmation (avoids window.confirm which can be silently blocked)
      if (!delBtn.dataset.armed) {
        delBtn.dataset.armed = '1';
        delBtn.textContent = '⚠️';
        delBtn.title = 'Click again to confirm delete';
        delBtn.style.background = 'var(--red)';
        setTimeout(() => {
          if (delBtn) { delete delBtn.dataset.armed; delBtn.textContent = '✕'; delBtn.style.background = ''; delBtn.title = 'Delete task'; }
        }, 3000);
        return;
      }
      delete delBtn.dataset.armed;
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

    // Forecast warning — show if event is > 7 days from today
    const warningEl = document.getElementById('task-forecast-warning');
    if (warningEl) {
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const taskDay = new Date(task.date + 'T00:00:00');
      const daysAway = Math.round((taskDay - today) / (1000 * 60 * 60 * 24));

      if (daysAway > 7) {
        warningEl.style.display = 'block';
        warningEl.className = 'task-forecast-warning';
        warningEl.innerHTML = `
          <span class="task-forecast-warning__icon">⚠️</span>
          <div class="task-forecast-warning__text">
            <strong>Forecast accuracy notice</strong><br>
            This event is <strong>${daysAway} days away</strong>. Weather and traffic conditions are harder to predict beyond 7 days — the AI advice above may not reflect actual conditions closer to the date. Consider reviewing again nearer the time.
          </div>
        `;
      } else {
        warningEl.style.display = 'none';
        warningEl.innerHTML = '';
      }
    }

    // Personal Notes
    const notesDisplay = document.getElementById('task-personal-notes-display');
    const notesEdit = document.getElementById('task-personal-notes-edit');
    const editBtn = document.getElementById('task-notes-edit-btn');
    const saveBtn = document.getElementById('task-notes-save-btn');
    const cancelBtn = document.getElementById('task-notes-cancel-btn');

    if (notesDisplay && notesEdit && editBtn && saveBtn && cancelBtn) {
      const currentNotes = task.personal_notes || '';
      
      // Reset UI to view mode
      notesDisplay.style.display = 'block';
      notesEdit.style.display = 'none';
      editBtn.style.display = 'inline-block';
      saveBtn.style.display = 'none';
      cancelBtn.style.display = 'none';

      let html = currentNotes || '<em style="color:var(--text-muted)">No personal notes yet.</em>';
      html = html.replace(/\n/g, '<br/>');
      notesDisplay.innerHTML = html;

      editBtn.onclick = () => {
        notesDisplay.style.display = 'none';
        notesEdit.style.display = 'block';
        notesEdit.value = currentNotes;
        editBtn.style.display = 'none';
        saveBtn.style.display = 'inline-block';
        cancelBtn.style.display = 'inline-block';
        notesEdit.focus();
      };

      cancelBtn.onclick = () => {
        notesDisplay.style.display = 'block';
        notesEdit.style.display = 'none';
        editBtn.style.display = 'inline-block';
        saveBtn.style.display = 'none';
        cancelBtn.style.display = 'none';
      };

      saveBtn.onclick = async () => {
        saveBtn.textContent = 'Saving...';
        saveBtn.disabled = true;
        try {
          const payload = {
            title: task.title,
            date: task.date,
            start_time: task.start_time,
            end_time: task.end_time,
            location: task.location || '',
            status: task.status,
            notes: task.notes || '', // keep AI rationale intact
            personal_notes: notesEdit.value
          };
          const res = await fetch(`/api/schedule/${task.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (res.ok) {
            // Re-fetch and re-render
            await loadTasks();
            render();
            // Re-open updated modal
            const updatedTask = tasks.find(t => t.id === task.id);
            if (updatedTask) _openTaskModal(updatedTask);
          } else {
            alert('Failed to save notes.');
          }
        } catch (err) {
          alert('Network error.');
        } finally {
          saveBtn.textContent = 'Save Notes';
          saveBtn.disabled = false;
        }
      };
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
    const btn = document.getElementById('task-details-delete-btn');
    // Two-click confirmation (avoids window.confirm which can be silently blocked)
    if (btn && !btn.dataset.armed) {
      btn.dataset.armed = '1';
      btn.textContent = '⚠️ Confirm Delete?';
      btn.style.background = 'var(--red)';
      setTimeout(() => {
        if (btn) { delete btn.dataset.armed; btn.textContent = '🗑 Delete Event'; btn.style.background = ''; }
      }, 3000);
      return;
    }
    if (btn) { delete btn.dataset.armed; btn.textContent = '🗑 Delete Event'; btn.style.background = ''; }
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

  // ── Conflict Resolution Modal ──────────────────────────────────────────────

  let _activeConflictData = null;

  async function _openConflictModal(taskA, taskB) {
    // Show loading state
    document.getElementById('conflict-modal-overlay').style.display = 'flex';
    document.getElementById('conflict-keep-title').textContent = 'Loading...';
    document.getElementById('conflict-move-title').textContent = 'Loading...';
    document.getElementById('conflict-rationale').textContent = 'Analyzing priorities and finding free slots...';
    document.getElementById('conflict-alternatives-container').style.display = 'none';

    try {
      const res = await fetch('/api/conflicts/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_a_id: taskA.id, task_b_id: taskB.id })
      });

      if (!res.ok) throw new Error('Failed to resolve');
      const data = await res.json();
      _activeConflictData = data;

      // Populate UI
      const k = data.keep_task;
      const m = data.move_task;

      document.getElementById('conflict-keep-title').textContent = k.title;
      document.getElementById('conflict-keep-time').textContent = `${k.start_time}${k.end_time ? '–' + k.end_time : ''}`;

      document.getElementById('conflict-move-title').textContent = m.title;
      document.getElementById('conflict-move-old-time').textContent = `${m.start_time}${m.end_time ? '–' + m.end_time : ''}`;

      const newTimeStr = `${data.suggested_start}–${data.suggested_end}`;
      const sameDay = data.suggested_date === m.date;
      document.getElementById('conflict-move-new-time').textContent = sameDay ? newTimeStr : `${newTimeStr} on ${data.suggested_date}`;

      // Format markdown in rationale
      let html = data.rationale;
      html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/\n/g, '<br/>');
      document.getElementById('conflict-rationale').innerHTML = html;

      // Alternatives
      const altsList = document.getElementById('conflict-alternatives-list');
      altsList.innerHTML = '';
      data.alternatives.forEach(alt => {
        const btn = document.createElement('button');
        btn.className = 'alt-chip';
        btn.textContent = `${alt.start}–${alt.end}${alt.date !== m.date ? ' (' + alt.date + ')' : ''}`;
        btn.onclick = () => {
          _activeConflictData.suggested_date = alt.date;
          _activeConflictData.suggested_start = alt.start;
          _activeConflictData.suggested_end = alt.end;
          const sd = alt.date === m.date;
          document.getElementById('conflict-move-new-time').textContent = sd ? `${alt.start}–${alt.end}` : `${alt.start}–${alt.end} on ${alt.date}`;
        };
        altsList.appendChild(btn);
      });

    } catch (err) {
      document.getElementById('conflict-rationale').textContent = 'Error loading resolution.';
    }
  }

  function _closeConflictModal() {
    document.getElementById('conflict-modal-overlay').style.display = 'none';
    _activeConflictData = null;
  }

  async function _acceptConflictResolution() {
    if (!_activeConflictData) return;
    const task = _activeConflictData.move_task;

    try {
      const payload = {
        title: task.title,
        date: _activeConflictData.suggested_date,
        start_time: _activeConflictData.suggested_start,
        end_time: _activeConflictData.suggested_end,
        location: task.location || '',
        notes: task.notes || ''
      };

      const res = await fetch(`/api/schedule/${task.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        _closeConflictModal();
        await refresh();
      } else {
        alert('Failed to reschedule task.');
      }
    } catch (err) {
      alert('Network error.');
    }
  }

  // ── Upcoming Schedule List (Right Sidebar) ─────────────────────────────────

  function _renderScheduleList() {
    const listEl = document.getElementById('schedule-list');
    if (!listEl) return;

    const now = new Date();
    const todayStr = formatDate(now);
    const nowMins = now.getHours() * 60 + now.getMinutes();

    // Sort all tasks: upcoming first (by date then start_time), then past at bottom
    const sorted = [...tasks].sort((a, b) => {
      const da = a.date + 'T' + (a.start_time || '00:00');
      const db = b.date + 'T' + (b.start_time || '00:00');
      return da < db ? -1 : da > db ? 1 : 0;
    });

    // Split into upcoming and past
    const upcoming = sorted.filter(t => {
      if (t.date > todayStr) return true;
      if (t.date === todayStr) return timeToMinutes(t.start_time || '00:00') >= nowMins;
      return false;
    });
    const past = sorted.filter(t => {
      if (t.date < todayStr) return true;
      if (t.date === todayStr) return timeToMinutes(t.start_time || '00:00') < nowMins;
      return false;
    });

    const combined = [...upcoming, ...past];

    if (combined.length === 0) {
      listEl.innerHTML = '<div class="schedule-list__empty">No scheduled events</div>';
      return;
    }

    listEl.innerHTML = '';
    combined.forEach(task => {
      const isPast = task.date < todayStr ||
        (task.date === todayStr && timeToMinutes(task.start_time || '00:00') < nowMins);

      const statusClass = isPast ? 'past' : (task.status || 'confirmed');

      // Format date nicely
      const dateObj = new Date(task.date + 'T00:00:00');
      const dateFmt = dateObj.toLocaleDateString('en-MY', { weekday: 'short', month: 'short', day: 'numeric' });
      const timeStr = task.start_time + (task.end_time ? ' – ' + task.end_time : '');

      const item = document.createElement('div');
      item.className = `schedule-item schedule-item--${statusClass}`;
      item.innerHTML = `
        <div class="schedule-item__info">
          <div class="schedule-item__title">${_escHtml(task.title)}</div>
          <div class="schedule-item__meta">${dateFmt}<br>${timeStr}${task.location ? ' · ' + _escHtml(task.location) : ''}</div>
        </div>
        <span class="schedule-item__arrow">›</span>
      `;

      item.addEventListener('click', () => {
        // Navigate calendar to the correct week
        const taskDate = new Date(task.date + 'T00:00:00');
        const todayMonday = getMondayOf(new Date());
        const taskMonday = getMondayOf(taskDate);
        const msPerWeek = 7 * 24 * 60 * 60 * 1000;
        const weekDiff = Math.round((taskMonday - todayMonday) / msPerWeek);

        currentWeekOffset = weekDiff;
        render(); // re-render calendar at the right week

        // Open the task details modal
        setTimeout(() => _openTaskModal(task), 50);
      });

      listEl.appendChild(item);
    });
  }

  function _escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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

    // Conflict Modal triggers
    document.getElementById('conflict-close')?.addEventListener('click', _closeConflictModal);
    document.getElementById('conflict-modal-overlay')?.addEventListener('click', e => {
      if (e.target === e.currentTarget) _closeConflictModal();
    });

    document.getElementById('conflict-accept-btn')?.addEventListener('click', _acceptConflictResolution);

    document.getElementById('conflict-manual-btn')?.addEventListener('click', () => {
      if (_activeConflictData && typeof Chat !== 'undefined') {
        const m = _activeConflictData.move_task;
        Chat.prefill(`Reschedule "${m.title}" to a better time`);
        _closeConflictModal();
      }
    });

    document.getElementById('conflict-alts-btn')?.addEventListener('click', () => {
      const cont = document.getElementById('conflict-alternatives-container');
      cont.style.display = cont.style.display === 'none' ? 'block' : 'none';
    });

    // Escape key
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        _closeTaskModal();
        _closeConflictModal();
      }
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
    document.getElementById('week-today')?.addEventListener('click', () => {
      currentWeekOffset = 0;
      render();
    });

    // Auto-update now line every minute
    setInterval(() => {
      const grid = document.getElementById('cal-grid');
      if (grid) {
        const today = new Date();
        today.setDate(today.getDate() + currentWeekOffset * 7);
        const dayOfWeek = today.getDay();
        const diff = today.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1);
        const startOfWeek = new Date(today.setDate(diff));
        
        const weekDates = [];
        for (let i = 0; i < 7; i++) {
          weekDates.push(new Date(startOfWeek.getTime() + i * 86400000));
        }
        _drawNowLine(grid, weekDates);
      }
    }, 60000);
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
