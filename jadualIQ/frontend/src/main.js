/**
 * main.js — App bootstrap.
 * Runs after all modules are loaded.
 * Checks auth, sets up user badge, initialises all modules.
 */
(async () => {
  // ── Auth gate ──────────────────────────────────────────────────────────────
  const user = await Auth.me();
  if (!user) {
    window.location.href = '/login';
    return;
  }

  // ── User badge ─────────────────────────────────────────────────────────────
  const initial = document.getElementById('user-initial');
  const name    = document.getElementById('user-menu-name');
  if (initial) initial.textContent = user.username[0].toUpperCase();
  if (name)    name.textContent    = user.username;

  // Toggle user menu on click
  const badge = document.getElementById('user-badge');
  badge?.addEventListener('click', e => {
    e.stopPropagation();
    badge.classList.toggle('open');
  });
  document.addEventListener('click', () => badge?.classList.remove('open'));

  // Logout
  document.getElementById('logout-btn')?.addEventListener('click', async () => {
    await Auth.logout();
    window.location.href = '/login';
  });

  // ── Initialise modules ─────────────────────────────────────────────────────
  Chat.init();
  Restrictions.init();
  await Calendar.init();
  Impact.start(30000);
})();
