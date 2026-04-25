import sqlite3
import hashlib
from config import DB_PATH


def get_db():
    """Return a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # VERCEL HACK: Disable foreign keys because /tmp database is ephemeral 
    # and the users table might be empty on a new serverless instance
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    c = conn.cursor()

    # ── Users ────────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL UNIQUE,
            email       TEXT    NOT NULL UNIQUE,
            password    TEXT    NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Tasks (schedule) ─────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT    NOT NULL,
            date        TEXT    NOT NULL,   -- YYYY-MM-DD
            start_time  TEXT    NOT NULL,   -- HH:MM
            end_time    TEXT,               -- HH:MM
            location    TEXT    DEFAULT '',
            status      TEXT    DEFAULT 'confirmed',  -- confirmed | warning | blocked
            notes       TEXT    DEFAULT '',
            personal_notes TEXT DEFAULT '',
            savings_rm  REAL    DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrate: add savings_rm if column is missing (existing databases)
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN savings_rm REAL DEFAULT 0")
    except Exception:
        pass  # column already exists
    # Migrate: add personal_notes
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN personal_notes TEXT DEFAULT ''")
    except Exception:
        pass

    # ── Restrictions ──────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS restrictions (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type    TEXT    NOT NULL,   -- 'day_block' | 'time_block' | 'location_limit' | 'custom'
            value   TEXT    NOT NULL,   -- e.g. 'Sunday', '00:00-09:00', free text
            label   TEXT    NOT NULL
        )
    """)

    # ── Impact Log ────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS impact_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_type  TEXT    NOT NULL,  -- 'task_scheduled' | 'conflict_avoided' | 'time_saved_minutes'
            value       REAL    DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ──────────────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_user(username: str, email: str, password: str) -> dict:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (username, email, hash_password(password))
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return {"id": row["id"], "username": row["username"], "email": row["email"]}
    except sqlite3.IntegrityError as e:
        raise ValueError(str(e))
    finally:
        conn.close()


def verify_user(username: str, password: str):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, hash_password(password))
    ).fetchone()
    conn.close()
    if row:
        return {"id": row["id"], "username": row["username"], "email": row["email"]}
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tasks (schedule)
# ──────────────────────────────────────────────────────────────────────────────

def get_tasks(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY date, start_time",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_task(user_id: int, data: dict, conflict_detected: bool = False) -> dict:
    conn = get_db()
    c = conn.execute(
        """INSERT INTO tasks (user_id, title, date, start_time, end_time, location, status, notes, personal_notes, savings_rm)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            data.get("title", "Untitled"),
            data.get("date", ""),
            data.get("start_time", "09:00"),
            data.get("end_time", "10:00"),
            data.get("location", ""),
            data.get("status", "confirmed"),
            data.get("rationale", data.get("notes", "")),
            data.get("personal_notes", ""),
            float(data.get("savings_rm", 0) or 0),
        )
    )
    task_id = c.lastrowid
    conn.commit()
    # Log the event
    conn.execute(
        "INSERT INTO impact_log (user_id, event_type, value) VALUES (?, 'task_scheduled', 1)",
        (user_id,)
    )
    # Estimate time saved from actual task duration (minutes)
    try:
        st = data.get("start_time", "09:00")
        et = data.get("end_time", "10:00")
        sh, sm = map(int, st.split(':'))
        eh, em = map(int, et.split(':'))
        duration_mins = max(30, (eh * 60 + em) - (sh * 60 + sm))
    except Exception:
        duration_mins = 30
    conn.execute(
        "INSERT INTO impact_log (user_id, event_type, value) VALUES (?, 'time_saved_minutes', ?)",
        (user_id, duration_mins)
    )
    # Log money saved from transport advice
    try:
        savings_rm = float(data.get("savings_rm", 0))
    except (ValueError, TypeError):
        savings_rm = 0.0
        
    if savings_rm > 0:
        conn.execute(
            "INSERT INTO impact_log (user_id, event_type, value) VALUES (?, 'money_saved_rm', ?)",
            (user_id, savings_rm)
        )
    # Log conflict avoided if this task overlapped with an existing one
    if conflict_detected:
        conn.execute(
            "INSERT INTO impact_log (user_id, event_type, value) VALUES (?, 'conflict_avoided', 1)",
            (user_id,)
        )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


def update_task(task_id: int, user_id: int, data: dict) -> dict | None:
    conn = get_db()
    conn.execute(
        """UPDATE tasks SET title=?, date=?, start_time=?, end_time=?, location=?, status=?, notes=?, personal_notes=?
           WHERE id=? AND user_id=?""",
        (
            data.get("title"),
            data.get("date"),
            data.get("start_time"),
            data.get("end_time"),
            data.get("location", ""),
            data.get("status", "confirmed"),
            data.get("notes", ""),
            data.get("personal_notes", ""),
            task_id,
            user_id,
        )
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_task(task_id: int, user_id: int) -> bool:
    conn = get_db()
    # Fetch the task first so we can reverse its impact
    row = conn.execute(
        "SELECT start_time, end_time, savings_rm FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, user_id)
    ).fetchone()

    c = conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    if c.rowcount > 0 and row:
        # Reverse time saved
        try:
            st = row["start_time"] or "09:00"
            et = row["end_time"] or "10:00"
            sh, sm = map(int, st.split(':'))
            eh, em = map(int, et.split(':'))
            duration_mins = max(30, (eh * 60 + em) - (sh * 60 + sm))
        except Exception:
            duration_mins = 30

        conn.execute(
            "INSERT INTO impact_log (user_id, event_type, value) VALUES (?, 'time_saved_minutes', ?)",
            (user_id, -duration_mins)
        )
        # Reverse money saved
        savings = float(row["savings_rm"] or 0)
        if savings > 0:
            conn.execute(
                "INSERT INTO impact_log (user_id, event_type, value) VALUES (?, 'money_saved_rm', ?)",
                (user_id, -savings)
            )
    conn.commit()
    conn.close()
    return c.rowcount > 0


def get_task_by_id(user_id: int, task_id: int) -> dict | None:
    """Fetch a single task belonging to user_id."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_conflicts_for_slot(
    user_id: int,
    date: str,
    start_time: str,
    end_time: str,
    exclude_task_id: int = None,
) -> list:
    """Return tasks on `date` whose time window overlaps [start_time, end_time].

    Overlap condition: existing.start < end_time  AND  existing.end > start_time
    If end_time is NULL in the DB it is treated as start_time + 60 min.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE user_id = ? AND date = ?",
        (user_id, date),
    ).fetchall()
    conn.close()

    def _to_mins(t: str) -> int:
        h, m = t.split(":")[:2]
        return int(h) * 60 + int(m)

    req_s = _to_mins(start_time)
    req_e = _to_mins(end_time)
    results = []
    for r in rows:
        row = dict(r)
        if exclude_task_id and row["id"] == exclude_task_id:
            continue
        t_s = _to_mins(row["start_time"])
        t_e = _to_mins(row["end_time"]) if row.get("end_time") else t_s + 60
        if t_s < req_e and t_e > req_s:
            results.append(row)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Restrictions
# ──────────────────────────────────────────────────────────────────────────────

def get_restrictions(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM restrictions WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_restriction(user_id: int, data: dict) -> dict:
    conn = get_db()
    c = conn.execute(
        "INSERT INTO restrictions (user_id, type, value, label) VALUES (?, ?, ?, ?)",
        (user_id, data.get("type", "custom"), data.get("value", ""), data.get("label", ""))
    )
    rid = c.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM restrictions WHERE id = ?", (rid,)).fetchone()
    conn.close()
    return dict(row)


def delete_restriction(restriction_id: int, user_id: int) -> bool:
    conn = get_db()
    c = conn.execute(
        "DELETE FROM restrictions WHERE id = ? AND user_id = ?",
        (restriction_id, user_id)
    )
    conn.commit()
    conn.close()
    return c.rowcount > 0


# ──────────────────────────────────────────────────────────────────────────────
# Impact
# ──────────────────────────────────────────────────────────────────────────────

def get_impact(user_id: int) -> dict:
    conn = get_db()

    # Tasks scheduled total
    tasks_total = conn.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE user_id = ?", (user_id,)
    ).fetchone()["cnt"]

    # Time saved this week — sum from impact_log using date-only comparison
    time_saved = conn.execute(
        """SELECT COALESCE(SUM(value), 0) as total FROM impact_log
           WHERE user_id = ? AND event_type = 'time_saved_minutes'
           AND date(created_at) >= date('now', '-7 days')""",
        (user_id,)
    ).fetchone()["total"]

    # Active conflicts — calculate real-time overlapping pairs for upcoming tasks
    tasks = conn.execute(
        "SELECT start_time, end_time, date FROM tasks WHERE user_id = ? AND date >= date('now', 'localtime')",
        (user_id,)
    ).fetchall()
    
    conflict_count = 0
    by_date = {}
    for t in tasks:
        by_date.setdefault(t["date"], []).append(t)
        
    for date_str, day_tasks in by_date.items():
        for i in range(len(day_tasks)):
            for j in range(i + 1, len(day_tasks)):
                t1, t2 = day_tasks[i], day_tasks[j]
                
                def _to_mins(t_time):
                    h, m = map(int, t_time.split(':'))
                    return h * 60 + m
                    
                s1 = _to_mins(t1["start_time"])
                e1 = _to_mins(t1["end_time"]) if t1["end_time"] else s1 + 60
                
                s2 = _to_mins(t2["start_time"])
                e2 = _to_mins(t2["end_time"]) if t2["end_time"] else s2 + 60
                
                if s1 < e2 and e1 > s2:
                    conflict_count += 1
                    
    conflicts = conflict_count

    # Money saved this week — sum from impact_log using date-only comparison
    money_saved = conn.execute(
        """SELECT COALESCE(SUM(value), 0) as total FROM impact_log
           WHERE user_id = ? AND event_type = 'money_saved_rm'
           AND date(created_at) >= date('now', '-7 days')""",
        (user_id,)
    ).fetchone()["total"]

    conn.close()

    return {
        "tasks_scheduled": tasks_total,
        "hours_saved_this_week": round(time_saved / 60, 1),
        "conflicts_today": conflicts,
        "rm_saved_this_week": round(money_saved, 2)
    }
