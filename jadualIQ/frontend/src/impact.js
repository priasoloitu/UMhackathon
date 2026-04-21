/**
 * impact.js — Fetches and updates the top-nav impact strip.
 */
const Impact = (() => {
  let refreshTimer = null;

  async function refresh() {
    try {
      const res  = await fetch('/api/impact', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();

      const hours     = document.getElementById('impact-hours-val');
      const tasks     = document.getElementById('impact-tasks-val');
      const conflicts = document.getElementById('impact-conflicts-val');
      const rm        = document.getElementById('impact-rm-val');

      if (hours)     hours.textContent     = data.hours_saved_this_week || 0;
      if (tasks)     tasks.textContent     = data.tasks_scheduled || 0;
      if (conflicts) conflicts.textContent = data.conflicts_today || 0;
      if (rm)        rm.textContent        = "RM " + (data.rm_saved_this_week || 0);
    } catch (_) {
      // silently ignore
    }
  }

  function start(intervalMs = 30000) {
    refresh();
    refreshTimer = setInterval(refresh, intervalMs);
  }

  function stop() {
    if (refreshTimer) clearInterval(refreshTimer);
  }

  return { refresh, start, stop };
})();
