"""
Orchestrator agent — full pipeline:
  user message → intent parse → weather → traffic → conflict check
  → constraint check → priority score → GLM system prompt → call GLM → return response
"""

import re
import json
import traceback
from datetime import datetime, timedelta
from agents import weather as weather_agent
from agents import traffic as traffic_agent
from models.schedule_store import get_restrictions, get_conflicts_for_slot, get_task_by_id
from config import ZAI_BASE_URL, ZAI_MODEL, ZAI_API_KEY
import requests


def _strip_trailing_commas(s: str) -> str:
    """Remove trailing commas before } or ] (handles nested cases)."""
    return re.sub(r',\s*([}\]])', r'\1', s)


def _repair_json(raw: str) -> dict:
    """Robustly parse AI-generated JSON that may contain common model quirks.
    Handles: Python literals (None/True/False), trailing commas,
    truncated JSON, single-quoted keys, and markdown fences.
    """
    # 1. Strip markdown fences
    s = raw.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()

    # 2. Extract first JSON object if there's surrounding text
    obj_start = s.find("{")
    if obj_start > 0:
        s = s[obj_start:]

    # 3. Replace Python literals with JSON equivalents
    s = re.sub(r'\bNone\b', 'null', s)
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)

    # 4. Replace single-quoted keys with double quotes
    s = re.sub(r"'([^']+)':", r'"\1":', s)

    # 5. Remove trailing commas before } or ]
    s = _strip_trailing_commas(s)

    # 6. Try to parse as-is
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 7. JSON is truncated — close any open strings first
    if s.count('"') % 2 != 0:
        s += '"'

    # 8. Close open braces/brackets
    s = _strip_trailing_commas(s)
    open_braces   = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')
    s += ']' * max(open_brackets, 0) + '}' * max(open_braces, 0)

    # 9. Re-run trailing comma strip AFTER brace-closing (this was the bug)
    s = _strip_trailing_commas(s)

    return json.loads(s)  # raise if still invalid after all repairs

# ─────────────────────────────────────────────────────────────────────────────
# Intent Validator
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize_intent(intent: dict) -> dict:
    """Silently fix AI-hallucinated impossible values by nulling them out.

    This runs BEFORE validation. If the AI invents an impossible time like
    '25:00' when the user never mentioned a time, we just clear it so the
    clarification prompt asks for it — instead of showing a scary error.
    """
    # ── Time sanitization ──────────────────────────────────────────────────
    time_str = intent.get("time")
    if time_str:
        try:
            parts = time_str.split(":")
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                intent["time"] = None  # null out, clarification will ask
        except (ValueError, IndexError):
            intent["time"] = None

    # ── Date sanitization ─────────────────────────────────────────────────
    date_str = intent.get("date")
    if date_str:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            intent["date"] = None  # impossible date (e.g. Feb 30) → ask again

    # ── Duration sanitization ─────────────────────────────────────────────
    dur = intent.get("duration_hours")
    if dur is not None:
        try:
            if float(dur) <= 0 or float(dur) > 24:
                intent["duration_hours"] = 1.0
        except (ValueError, TypeError):
            intent["duration_hours"] = 1.0

    return intent


def _validate_intent(intent: dict, original_message: str = "") -> list[str]:
    """Validate intent for values the USER explicitly typed that are impossible.

    Only returns errors for things clearly in the user's raw message.
    AI-hallucinated bad values should already have been nulled by _sanitize_intent.
    """
    errors = []
    msg = original_message.lower()

    # ── Past date (user explicitly asked for a past date) ──────────────────
    date_str = intent.get("date")
    if date_str:
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
            if parsed_date.date() < datetime.now().date():
                errors.append(
                    f"The date **{date_str}** is in the past. "
                    "Did you mean a future date?"
                )
        except ValueError:
            pass  # already nulled by sanitize; won't reach here normally

    # ── Explicitly impossible time the USER typed (e.g. "at 25 AM") ───────
    # Only flag if the bad hour literally appears in the user's message
    time_str = intent.get("time")
    if time_str:
        try:
            hour = int(time_str.split(":")[0])
            minute = int(time_str.split(":")[1])
            if not (0 <= hour <= 23) and str(hour) in msg:
                errors.append(
                    f"**{time_str}** is not a valid time — "
                    "hour must be between 00 and 23."
                )
            if not (0 <= minute <= 59) and str(minute) in msg:
                errors.append(
                    f"**{time_str}** has invalid minutes — "
                    "minutes must be between 00 and 59."
                )
        except (ValueError, IndexError):
            pass

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Missing-field tracking
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = ["task_name", "date", "time"]

CLARIFICATION_PROMPTS = {
    "task_name": "What would you like to schedule? (e.g. meeting, doctor appointment, study session)",
    "date":      "Which date? (e.g. 'this Monday', 'April 25', or 'tomorrow')",
    "time":      "What time do you prefer? (e.g. '3pm', '09:00', 'morning')",
}

DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "isnin": 0, "selasa": 1, "rabu": 2, "khamis": 3,
    "jumaat": 4, "sabtu": 5, "ahad": 6,
}


def _merge_history_intent(current_intent: dict, history: list) -> dict:
    """Scan past user messages and fill in any fields missing from the current intent.

    This prevents the clarification loop where the AI re-parses a single reply
    like 'april 29' and forgets the task_name='meeting' from an earlier turn.
    We NEVER overwrite a field that current_intent already has.
    """
    MERGEABLE = ["task_name", "date", "time", "duration_hours", "location", "origin"]

    # Collect field values from all past user messages (oldest first)
    for h in history:
        if h.get("role") != "user":
            continue
        past = parse_intent(h["content"])
        for field in MERGEABLE:
            # Only fill fields that are currently missing
            if not current_intent.get(field) and past.get(field):
                current_intent[field] = past[field]

    return current_intent


# ─────────────────────────────────────────────────────────────────────────────
# Intent parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_intent(message: str, history: list = None) -> dict:
    """Extract scheduling intent from user message. Returns partial info if missing."""
    history = history or []
    msg = message.lower()
    intent = {
        "task_name": None,
        "date": None,
        "time": None,
        "duration_hours": 1,
        "location": None,
    }

    # ── Task name ─────────────────────────────────────────────────────────────
    # If the user is answering a clarification for task name
    if history and history[-1].get("role") == "assistant" and "What would you like to schedule?" in history[-1].get("content", ""):
        # User's current message is exactly the task name
        intent["task_name"] = message.strip().title()

    task_patterns = [
        r"schedule (?:a |an |my )?(.+?) (?:on|at|for|this|next|tomorrow|today)",
        r"book (?:a |an )?(.+?) (?:on|at|for)",
        r"set (?:up )?(?:a |an )?(.+?) (?:on|at|for)",
        r"(?:add|create) (?:a |an )?(.+?) (?:on|at|for)",
        r"(?:jadualkan|tetapkan) (.+?) (?:pada|hari|pukul)",
        r"(?:go to|visit|pergi ke) (.+?) (?:on|at|pada|hari)",
    ]
    if not intent["task_name"]:
        for p in task_patterns:
            m = re.search(p, msg)
            if m:
                intent["task_name"] = m.group(1).strip().title()
                break

    # ── Date ──────────────────────────────────────────────────────────────────
    today = datetime.now()

    if "today" in msg or "hari ini" in msg:
        intent["date"] = today.strftime("%Y-%m-%d")
    elif "tomorrow" in msg or "esok" in msg:
        intent["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "lusa" in msg:
        intent["date"] = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    else:
        # ── Priority 1: ISO date YYYY-MM-DD ────────────────────────────────────
        iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", msg)
        if iso:
            intent["date"] = iso.group(1)

        # ── Priority 2: "D Month [Year]" or "Month D [Year]" (e.g. "2 May", "May 2", "2nd May 2026")
        MONTHS = {
            "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
            "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
            "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,
            "aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
            "januari":1,"februari":2,"mac":3,"mei":5,"julai":7,
            "ogos":8,"september":9,"oktober":10,"november":11,"disember":12,
        }
        if not intent["date"]:
            # "2 May 2026", "2nd May", "2 May"
            dm_text = re.search(
                r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS.keys()) + r")(?:\s+(\d{4}))?\b",
                msg
            )
            if dm_text:
                day = int(dm_text.group(1))
                month = MONTHS[dm_text.group(2)]
                year = int(dm_text.group(3)) if dm_text.group(3) else today.year
                # Roll to next year if the date has already passed this year
                try:
                    candidate = today.replace(year=year, month=month, day=day)
                    if candidate.date() < today.date() and not dm_text.group(3):
                        candidate = candidate.replace(year=year + 1)
                    intent["date"] = candidate.strftime("%Y-%m-%d")
                except ValueError:
                    pass

            # "May 2", "May 2nd 2026"
            md_text = re.search(
                r"\b(" + "|".join(MONTHS.keys()) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?\b",
                msg
            )
            if md_text and not intent["date"]:
                month = MONTHS[md_text.group(1)]
                day = int(md_text.group(2))
                year = int(md_text.group(3)) if md_text.group(3) else today.year
                try:
                    candidate = today.replace(year=year, month=month, day=day)
                    if candidate.date() < today.date() and not md_text.group(3):
                        candidate = candidate.replace(year=year + 1)
                    intent["date"] = candidate.strftime("%Y-%m-%d")
                except ValueError:
                    pass

        # ── Priority 3: DD/MM or D/M numeric ───────────────────────────────────
        if not intent["date"]:
            dm = re.search(r"\b(\d{1,2})[/\-](\d{1,2})\b", msg)
            if dm:
                try:
                    d = int(dm.group(1)); mo = int(dm.group(2))
                    intent["date"] = today.replace(month=mo, day=d).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        # ── Priority 4: Named day — only if NO explicit date found above ────────
        if not intent["date"]:
            for day_name, day_num in DAYS.items():
                if day_name in msg:
                    days_ahead = (day_num - today.weekday()) % 7
                    if days_ahead == 0:
                        days_ahead = 7
                    if "next" in msg:
                        days_ahead += 7
                    intent["date"] = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                    break

    # ── Time ──────────────────────────────────────────────────────────────────
    t12 = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", msg)
    t24 = re.search(r"\b(\d{1,2}):(\d{2})\b", msg)

    if t12:
        hour = int(t12.group(1))
        minute = int(t12.group(2)) if t12.group(2) else 0
        if t12.group(3) == "pm" and hour < 12:
            hour += 12
        if t12.group(3) == "am" and hour == 12:
            hour = 0
        intent["time"] = f"{hour:02d}:{minute:02d}"
    elif t24:
        intent["time"] = f"{int(t24.group(1)):02d}:{t24.group(2)}"
    elif "morning" in msg or "pagi" in msg:
        intent["time"] = "09:00"
    elif "noon" in msg or "tengahari" in msg:
        intent["time"] = "12:00"
    elif "afternoon" in msg or "petang" in msg:
        intent["time"] = "14:00"
    elif "evening" in msg:
        intent["time"] = "17:00"
    elif "night" in msg or "malam" in msg:
        intent["time"] = "20:00"

    # ── Duration ──────────────────────────────────────────────────────────────
    dur = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr|jam)", msg)
    if dur:
        intent["duration_hours"] = float(dur.group(1))

    # ── Location ──────────────────────────────────────────────────────────────
    loc = re.search(r"(?:at|in|@|di|to)\s+([A-Za-z][A-Za-z\s]{2,30}?)(?:\s+at|\s+on|$|,|\.|!)", message)
    if loc:
        intent["location"] = loc.group(1).strip()

    # Special handling for the interactive location prompt UI
    if "proceed without location" in msg:
        intent["_skip_location_prompt"] = True
        
    orig_dest = re.search(r"origin:\s*(.*?),\s*destination:\s*(.*)", msg, re.IGNORECASE)
    if orig_dest:
        intent["origin"] = orig_dest.group(1).strip()
        intent["location"] = orig_dest.group(2).strip()
        intent["_skip_location_prompt"] = True

    return intent


def get_missing_fields(intent: dict) -> list:
    """Return list of required fields that are still None."""
    return [f for f in REQUIRED_FIELDS if not intent.get(f)]


CLARIFICATION_SYSTEM_PROMPT = """You are JadualIQ, a friendly AI scheduling assistant.
The user wants to schedule something, but they forgot to provide some required information.
You already know the following about their intent:
{intent_json}

The following fields are MISSING:
{missing_fields}

Your task is to write a short, friendly, and conversational single-sentence question asking the user to provide the missing information. 
Do NOT confirm the appointment yet. Just ask for what is missing.
Respond ONLY with the question itself. No quotes, no formatting."""

def generate_clarification_message(intent: dict, missing: list) -> str:
    """Agentic clarification prompt generator. Falls back to static dictionary."""
    field = missing[0]
    fallback_msg = CLARIFICATION_PROMPTS.get(field, f"Could you provide the {field}?")
    
    if not ZAI_API_KEY:
        return fallback_msg
        
    system_prompt = CLARIFICATION_SYSTEM_PROMPT.format(
        intent_json=json.dumps({k: v for k, v in intent.items() if v is not None}, indent=2),
        missing_fields=", ".join(missing)
    )
    
    try:
        headers = {
            "Authorization": f"Bearer {ZAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": ZAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Please generate the clarification question."}
            ],
            "temperature": 0.4,
            "max_tokens": 100,
        }
        resp = None
        for attempt, timeout in enumerate([15, 25], start=1):
            try:
                resp = requests.post(f"{ZAI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=timeout)
                break
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise
                print(f"[clarification_agent] Attempt {attempt} timed out, retrying...")
        resp.raise_for_status()
        
        resp_json = resp.json()
        if not resp_json.get("choices") or not resp_json["choices"][0].get("message"):
            return fallback_msg
            
        raw = resp_json["choices"][0]["message"].get("content") or ""
        
        clean_msg = raw.strip().strip('"').strip("'")
        if clean_msg:
            return clean_msg
        return fallback_msg
    except Exception as e:
        print(f"[clarification_agent] Error: {e} - falling back to static prompt")
        return fallback_msg


# ─────────────────────────────────────────────────────────────────────────────
# Constraint checker
# ─────────────────────────────────────────────────────────────────────────────

def check_constraints(user_id: int, intent: dict) -> dict:
    """Check user restrictions against the parsed intent."""
    restrictions = get_restrictions(user_id)
    violations = []

    date_str = intent.get("date", "")
    time_str = intent.get("time", "")
    location = intent.get("location", "")

    if date_str:
        try:
            day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
        except ValueError:
            day_name = ""

        for r in restrictions:
            if r["type"] == "day_block" and r["value"].lower() == day_name.lower():
                violations.append(f"You have blocked {day_name}s.")
            elif r["type"] == "time_block" and time_str:
                parts = r["value"].split("-")
                if len(parts) == 2:
                    try:
                        block_start = datetime.strptime(parts[0].strip(), "%H:%M").time()
                        block_end   = datetime.strptime(parts[1].strip(), "%H:%M").time()
                        req_time    = datetime.strptime(time_str, "%H:%M").time()
                        if block_start <= req_time < block_end:
                            violations.append(f"Time block: {r['label']}")
                    except ValueError:
                        pass
            elif r["type"] == "location_limit" and location:
                if r["value"].lower() not in location.lower():
                    violations.append(f"Location restriction: {r['label']}")

    custom_rules = [r["value"] for r in restrictions if r["type"] == "custom"]

    return {
        "violations": violations,
        "custom_rules": custom_rules,
        "status": "blocked" if violations else "ok",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Priority scorer fallback
# ─────────────────────────────────────────────────────────────────────────────

def score_priority(intent: dict, message: str) -> int:
    """Fallback priority scorer when AI is unavailable."""
    return 5


# ─────────────────────────────────────────────────────────────────────────────
# Conflict Resolution
# ─────────────────────────────────────────────────────────────────────────────

def _find_next_free_slot(
    user_id: int,
    date: str,
    after_time: str,
    duration_hours: float = 1.0,
    exclude_task_id: int = None,
) -> dict:
    """Search forward (hourly) from after_time for the next free slot.
    Falls back to next morning 09:00 if nothing is free today before 22:00.
    """
    dur = max(60, int(duration_hours * 60))
    h, m = int(after_time[:2]), int(after_time[3:5])
    cur = h * 60 + m

    while cur + dur <= 22 * 60:
        s = f"{cur // 60:02d}:{cur % 60:02d}"
        e = f"{(cur + dur) // 60:02d}:{(cur + dur) % 60:02d}"
        if not get_conflicts_for_slot(user_id, date, s, e, exclude_task_id):
            return {"date": date, "start": s, "end": e}
        cur += 60

    # Nothing today — try next morning
    next_d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    end_h = 9 + int(duration_hours)
    return {"date": next_d, "start": "09:00", "end": f"{end_h:02d}:00"}


CONFLICT_RESOLUTION_PROMPT = """You are JadualIQ, an AI scheduling assistant resolving a calendar conflict.

Two tasks overlap on the calendar:
Task A: "{title_a}" (ID: {id_a}) at {start_a}–{end_a}
Task B: "{title_b}" (ID: {id_b}) at {start_b}–{end_b}

Evaluate their importance. You are the sole decision-maker.
If we move Task A, its best alternative slot is {alt_a_start}–{alt_a_end} on {alt_a_date}.
If we move Task B, its best alternative slot is {alt_b_start}–{alt_b_end} on {alt_b_date}.

Decide which task to KEEP at its original time, and which to MOVE.
Respond ONLY with valid JSON:
{{
  "keep_task_id": 123,
  "move_task_id": 456,
  "keep_score": 9,
  "move_score": 4,
  "rationale": "2-3 sentence friendly explanation of why we keep the chosen task and move the other to its new slot. Use **bold** for task names and times."
}}"""


def resolve_conflict(user_id: int, task_a_id: int, task_b_id: int) -> dict | None:
    """AI-powered conflict resolution: decides which task to keep vs move."""
    task_a = get_task_by_id(user_id, task_a_id)
    task_b = get_task_by_id(user_id, task_b_id)
    if not task_a or not task_b:
        return None

    # Calculate durations
    def _get_dur(t):
        if t.get("end_time") and t["end_time"] != t["start_time"]:
            s = int(t["start_time"][:2]) * 60 + int(t["start_time"][3:5])
            e = int(t["end_time"][:2]) * 60 + int(t["end_time"][3:5])
            return max(1.0, (e - s) / 60)
        return 1.0

    dur_a = _get_dur(task_a)
    dur_b = _get_dur(task_b)

    # Find alternatives for BOTH tasks so the AI can weigh the options
    after_b = task_b.get("end_time") or f"{int(task_b['start_time'][:2]) + 1:02d}:{task_b['start_time'][3:5]}"
    alt_for_a = _find_next_free_slot(user_id, task_a["date"], after_b, dur_a, task_a_id)
    
    after_a = task_a.get("end_time") or f"{int(task_a['start_time'][:2]) + 1:02d}:{task_a['start_time'][3:5]}"
    alt_for_b = _find_next_free_slot(user_id, task_b["date"], after_a, dur_b, task_b_id)

    prompt = CONFLICT_RESOLUTION_PROMPT.format(
        title_a=task_a["title"], id_a=task_a["id"], start_a=task_a["start_time"], end_a=task_a.get("end_time") or "",
        title_b=task_b["title"], id_b=task_b["id"], start_b=task_b["start_time"], end_b=task_b.get("end_time") or "",
        alt_a_start=alt_for_a["start"], alt_a_end=alt_for_a["end"], alt_a_date=alt_for_a["date"],
        alt_b_start=alt_for_b["start"], alt_b_end=alt_for_b["end"], alt_b_date=alt_for_b["date"],
    )

    keep_id, move_id = task_a["id"], task_b["id"]
    keep_score, move_score = 10, 5
    rationale = f"We kept **{task_a['title']}** and moved **{task_b['title']}** to {alt_for_b['start']} on {alt_for_b['date']}."

    if ZAI_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {ZAI_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": ZAI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 256}
            resp = requests.post(f"{ZAI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            resp_json = resp.json()
            if resp_json.get("choices") and resp_json["choices"][0].get("message"):
                raw = resp_json["choices"][0]["message"].get("content") or ""
                clean_raw = raw.strip()
                if clean_raw.startswith("```json"): clean_raw = clean_raw[7:]
                elif clean_raw.startswith("```"): clean_raw = clean_raw[3:]
                if clean_raw.endswith("```"): clean_raw = clean_raw[:-3]
                parsed = json.loads(clean_raw.strip())
                keep_id = parsed.get("keep_task_id", keep_id)
                move_id = parsed.get("move_task_id", move_id)
                keep_score = parsed.get("keep_score", keep_score)
                move_score = parsed.get("move_score", move_score)
                rationale = parsed.get("rationale", rationale)
        except Exception as e:
            print(f"[resolve_conflict] AI error: {e}")

    # Map IDs back to tasks
    if keep_id == task_b["id"]:
        keep_task, move_task = task_b, task_a
        primary = alt_for_a
        dur_move = dur_a
    else:
        keep_task, move_task = task_a, task_b
        primary = alt_for_b
        dur_move = dur_b

    # Two additional alternatives for the moved task
    alt_after = primary["end"] if primary["date"] == move_task["date"] else "09:00"
    alt1 = _find_next_free_slot(user_id, primary["date"], alt_after, dur_move, move_task["id"])
    alt2_after = alt1["end"] if alt1["date"] == primary["date"] else "11:00"
    alt2 = _find_next_free_slot(user_id, alt1["date"], alt2_after, dur_move, move_task["id"])
    alternatives = [alt1, alt2]

    return {
        "keep_task":       keep_task,
        "move_task":       move_task,
        "keep_score":      keep_score,
        "move_score":      move_score,
        "suggested_date":  primary["date"],
        "suggested_start": primary["start"],
        "suggested_end":   primary["end"],
        "rationale":       rationale,
        "alternatives":    alternatives,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GLM caller
# ─────────────────────────────────────────────────────────────────────────────

GLM_SYSTEM_PROMPT_TEMPLATE = """You are JadualIQ, a smart schedule assistant.
Your ONLY job is to help users plan and manage their daily schedule.

You have access to the following context about the user's request:
- Task: {task_name}
- Requested date: {date}
- Requested time: {time}
- Duration: {duration_hours} hour(s)
- Location: {location}
- Weather forecast: {weather_summary}
- Traffic info: {traffic_summary}
- User restrictions: {restrictions_summary}
- Priority score: {priority}/10

{custom_rules_section}

Based on this context, suggest the optimal time slot for the user's task.
CRITICAL: You are the sole decision-maker. 
1. If the request violates ANY of the 'User restrictions' or 'custom rules', you MUST set "status" to "blocked".
2. If there are 'Calendar conflicts' or bad weather/traffic, you MUST set "status" to "warning".
3. Provide a detailed Transport Rationale:
  a. If the weather is bad (heavy rain) or traffic is crowded, actively advise the user to take Public Transport (LRT, MRT, BRT, etc.) instead of a car or Grab.
  b. Estimate the money saved. (For example, Grab might cost RM35, while public transit costs RM3. Say: "By taking public transit instead of Grab, you can save roughly RM32.")
  c. In the UI, this rationale will be shown fully. Make it polite and helpful.

Format your response as JSON with exactly these fields:
{{
  "suggestion": {{
    "title": "task title",
    "date": "YYYY-MM-DD",
    "start_time": "HH:MM",
    "end_time": "HH:MM",
    "location": "location or empty string",
    "status": "confirmed or warning or blocked",
    "notes": "brief 1 sentence note",
    "rationale": "A detailed 2-3 paragraph string explaining the transport mode, weather/traffic conditions, optimal departure time, and money saved. Use Markdown if helpful.",
    "savings_rm": 32
  }},
  "explanation": "1-2 sentence explanation for chat bubble",
  "alternatives": []
}}
Respond in the same language the user used (Malay or English).
IMPORTANT: If the user asks anything unrelated to scheduling, reply ONLY with:
{{"error": "I can only help you schedule your activities."}}"""


def call_glm(messages: list, system_prompt: str, intent: dict = None, weather_data: dict = None, traffic_data: dict = None) -> str:
    """Call Z.AI GLM and return the response text. Falls back to mock on any error."""
    if not ZAI_API_KEY:
        return _mock_glm_response(messages, intent, weather_data, traffic_data)

    try:
        headers = {
            "Authorization": f"Bearer {ZAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": ZAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }
        resp = None
        for attempt, timeout in enumerate([15, 25], start=1):
            try:
                resp = requests.post(
                    f"{ZAI_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                break  # success
            except requests.exceptions.Timeout:
                if attempt == 2:
                    print("[call_glm] Both attempts timed out — falling back to mock")
                    return _mock_glm_response(messages, intent, weather_data, traffic_data)
                print(f"[call_glm] Attempt {attempt} timed out, retrying with longer timeout...")
        resp.raise_for_status()
        resp_json = resp.json()
        if not resp_json.get("choices") or not resp_json["choices"][0].get("message"):
            raise ValueError("Empty or invalid GLM API response")
        raw = resp_json["choices"][0]["message"].get("content") or ""
        if not raw.strip():
            print("[call_glm] Z.AI returned empty content body — falling back to mock")
            return _mock_glm_response(messages, intent, weather_data, traffic_data)
        return raw
    except Exception as e:
        # API unreachable, quota exceeded, bad response — fall back to mock
        print(f"[orchestrator] Z.AI API error: {e} — falling back to mock response")
        return _mock_glm_response(messages, intent, weather_data, traffic_data)


def _mock_glm_response(messages: list, intent: dict = None, weather_data: dict = None, traffic_data: dict = None) -> str:
    """Return a mock GLM response when no API key is set (for development)."""
    import json
    today = datetime.now()
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    req_time = intent.get("time") if intent and intent.get("time") else "14:00"
    req_date = intent.get("date") if intent and intent.get("date") else tomorrow
    task_name = intent.get("task_name") if intent and intent.get("task_name") else "Scheduled Task"
    
    # Calculate departure time and end time
    try:
        hr = int(req_time.split(":")[0])
        minute = req_time.split(":")[1]
        depart_hr = hr - 1
        departure_time = f"{depart_hr:02d}:{minute}"
        # 12hr format for text
        depart_12 = f"{depart_hr if depart_hr <= 12 else depart_hr - 12} {'AM' if depart_hr < 12 else 'PM'}"
        req_12 = f"{hr if hr <= 12 else hr - 12} {'AM' if hr < 12 else 'PM'}"
        
        dur_h = intent.get("duration_hours", 1.0) if intent else 1.0
        total_mins = hr * 60 + int(minute) + int(dur_h * 60)
        end_hr = total_mins // 60
        end_min = total_mins % 60
        end_time = f"{end_hr:02d}:{end_min:02d}" if end_hr < 24 else "23:59"
    except:
        departure_time = "14:00"
        depart_12 = "2 PM"
        req_12 = "3 PM"
        end_time = "16:00"

    # Use simulated data to build dynamic rationale
    is_raining = weather_data and weather_data.get("rain_probability", 0) > 0.4
    is_heavy_traffic = traffic_data and traffic_data.get("peak_hour_warning", False)
    
    if is_raining or is_heavy_traffic:
        transport_mode = "Public Transport (LRT/MRT)"
        savings = 25 if is_heavy_traffic else 15
        reason = "heavy rain" if is_raining else "peak hour traffic"
        if is_raining and is_heavy_traffic:
            reason = "heavy rain and peak hour traffic"
        rationale = f"Based on the forecast, there will be {reason}. We strongly recommend leaving at **{depart_12}** and taking **{transport_mode}** to avoid delays. You'll also save roughly RM {savings} on ride-hailing fares."
        bubble_text = f"Since there will be {reason}, I suggest taking the LRT to save RM {savings}!"
    else:
        transport_mode = "Driving / Grab"
        savings = 0
        rationale = f"The weather looks clear and traffic is moderate. **{transport_mode}** is a good option for arriving at {task_name} on time. You can leave comfortably around **{depart_12}**."
        bubble_text = f"Weather and traffic are clear, so driving is a good option."

    return json.dumps({
        "suggestion": {
            "title": task_name,
            "date": req_date,
            "start_time": req_time,
            "end_time": end_time,
            "location": intent.get("location", "Kuala Lumpur") if intent else "Kuala Lumpur",
            "status": "warning" if (is_raining or is_heavy_traffic) else "confirmed",
            "notes": "Mock response — set ZAI_API_KEY for live GLM responses.",
            "rationale": rationale,
            "savings_rm": savings
        },
        "explanation": (
            f"I scheduled '{task_name}' for {req_12}. {bubble_text}"
        ),
        "alternatives": [
            {"date": req_date, "start_time": departure_time, "end_time": req_time},
        ],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Intake Agent (Unified Guardrail, Intent Parsing, and Priority)
# ─────────────────────────────────────────────────────────────────────────────

INTAKE_SYSTEM_PROMPT = """You are JadualIQ's Intake Agent. Extract scheduling intent from the user's message and conversation history.

Current Date/Time: {current_datetime}

Rules:
1. is_scheduling_related: true if the user wants to schedule/plan/check availability or is answering a scheduling clarification. False ONLY for purely off-topic questions.
2. intent: Extract task_name, date (YYYY-MM-DD), time (HH:MM 24h), duration_hours (float, NOT null — default 1.0 if not mentioned), location (string or null), origin (string or null). Set _skip_location_prompt true only if user says to skip/proceed without location.
3. If user is replying to a clarification, merge with previous intent from history.
4. priority_score: 10=emergency, 9=doctor/exam/interview, 7=work/class, 5=lunch/gym, 4=hobby.
5. IMPORTANT: Keep guardrail_reason under 8 words. Keep priority_reason under 6 words. This is critical to avoid truncation.

Return ONLY raw JSON (no markdown), EXACTLY this shape:
{{
  "is_scheduling_related": true,
  "guardrail_reason": "5 words max",
  "intent": {{
    "task_name": "string or null",
    "date": "YYYY-MM-DD or null",
    "time": "HH:MM or null",
    "duration_hours": 1.0,
    "location": "string or null",
    "origin": "string or null",
    "_skip_location_prompt": false
  }},
  "priority_score": 5,
  "priority_reason": "5 words max"
}}
"""

def _intake_fallback(message: str, history: list) -> dict:
    from agents.guardrail import is_scheduling_related
    
    is_sched = True
    if history and history[-1].get("role") == "assistant" and any(q in history[-1].get("content", "") for q in ["What would you like", "Which date", "What time", "location and destination"]):
        pass
    else:
        is_sched = is_scheduling_related(message) or "proceed without location" in message.lower() or "origin:" in message.lower()
        
    intent = {"task_name": None, "date": None, "time": None, "duration_hours": 1, "location": None}
    for h in history:
        if h["role"] == "user":
            step_intent = parse_intent(h["content"])
            # Merge new fields INTO existing intent — never reset
            for k in ["task_name", "date", "time", "duration_hours", "location", "origin", "_skip_location_prompt"]:
                if hasattr(step_intent, 'get') and step_intent.get(k):
                    intent[k] = step_intent[k]

    current_intent = parse_intent(message, history)
    # Merge current message fields on top
    for k in ["task_name", "date", "time", "duration_hours", "location", "origin", "_skip_location_prompt"]:
        if current_intent.get(k):
            intent[k] = current_intent[k]
            
    priority = score_priority(intent, message)
    
    return {
        "is_scheduling_related": is_sched,
        "guardrail_reason": "Fallback regex check",
        "intent": intent,
        "priority_score": priority,
        "priority_reason": "Fallback keyword check"
    }

def call_intake_agent(message: str, history: list) -> dict:
    """Call Z.AI to perform unified Intake: Guardrail + Intent + Priority."""
    if not ZAI_API_KEY:
        return _intake_fallback(message, history)

    system_prompt = INTAKE_SYSTEM_PROMPT.format(
        current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    
    # Only send the last 6 messages to avoid bloating Intake agent context
    glm_messages = history[-6:] + [{"role": "user", "content": message}]
    
    try:
        headers = {
            "Authorization": f"Bearer {ZAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": ZAI_MODEL,
            "messages": [{"role": "system", "content": system_prompt}] + glm_messages,
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        resp = None
        for attempt, timeout in enumerate([15, 25], start=1):
            try:
                resp = requests.post(f"{ZAI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=timeout)
                break  # success
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise  # re-raise after final attempt
                print(f"[intake_agent] Attempt {attempt} timed out, retrying with longer timeout...")
        resp.raise_for_status()
        resp_json = resp.json()
        if not resp_json.get("choices") or not resp_json["choices"][0].get("message"):
            raise ValueError("Empty or invalid API response")
        raw = resp_json["choices"][0]["message"].get("content") or ""

        if not raw.strip():
            raise ValueError("Z.AI returned an empty response body (server overloaded)")

        print(f"[intake_agent] Raw AI response: {raw[:600]}")
        parsed = _repair_json(raw)
        
        intent = parsed.get("intent", {})
        if "duration_hours" not in intent or not intent["duration_hours"]:
            intent["duration_hours"] = 1.0
            
        return {
            "is_scheduling_related": parsed.get("is_scheduling_related", True),
            "guardrail_reason": parsed.get("guardrail_reason", ""),
            "intent": intent,
            "priority_score": parsed.get("priority_score", 5),
            "priority_reason": parsed.get("priority_reason", "")
        }
    except Exception as e:
        print(f"[intake_agent] Error: {e} - falling back to regex")
        return _intake_fallback(message, history)


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run(user_id: int, message: str, history: list) -> dict:
    """
    Full orchestration pipeline.
    Returns a dict with keys: type, payload, clarification_needed, missing_fields
    """
    try:
        return _run_pipeline(user_id, message, history)
    except Exception as e:
        print(f"[orchestrator] UNHANDLED CRASH in run(): {e}")
        traceback.print_exc()
        return {
            "type": "warning",
            "message": "Something went wrong on the server. Please try again."
        }


def _run_pipeline(user_id: int, message: str, history: list) -> dict:
    """Inner pipeline — wrapped by run() for safe error handling."""
    # 1. Intake Agent (Unified Guardrail, Intent, Priority)
    intake_result = call_intake_agent(message, history)
    
    # 1.5. Guardrail Check
    if not intake_result.get("is_scheduling_related", True):
        return {
            "type": "warning",
            "message": (
                "I can only help you schedule your activities 📅\n\n"
                "Try something like:\n"
                "• \"Schedule a meeting on Wednesday at 3pm\"\n"
                "• \"I'm free on Thursday morning\"\n"
                "• \"Block Friday afternoon for study\"\n"
                "• \"Jadualkan mesyuarat hari Rabu pukul 3 petang\""
            )
        }
        
    intent = intake_result["intent"]
    priority = intake_result["priority_score"]

    # 1.6b Merge any missing fields from past user messages in history
    # Prevents the loop where AI forgets task_name from 3 turns ago when user just says "april 29"
    intent = _merge_history_intent(intent, history)

    # 1.7 Sanitize AI hallucinations, then Validate explicit user inputs
    intent = _sanitize_intent(intent)
    validation_errors = _validate_intent(intent, original_message=message)
    if validation_errors:
        error_text = "\n".join(f"• {e}" for e in validation_errors)
        return {
            "type": "warning",
            "message": f"I couldn't schedule that because the request doesn't seem valid:\n\n{error_text}\n\nPlease correct the details and try again."
        }

    # 1.8 Override _skip_location_prompt based on CURRENT message only
    msg_lower_check = message.lower()
    is_skip_msg = any(w in msg_lower_check for w in ["proceed without", "skip location", "no location", "without location"])
    is_location_input = "origin:" in msg_lower_check or "destination:" in msg_lower_check
    intent["_skip_location_prompt"] = is_skip_msg or is_location_input


    # 2. Check for missing required fields — ask user instead of guessing
    # Also treat vague/placeholder task names as missing
    VAGUE_TASK_NAMES = {"something", "anything", "task", "event", "stuff", "thing", "it"}
    if intent.get("task_name", "").strip().lower() in VAGUE_TASK_NAMES:
        intent["task_name"] = None  # force clarification

    missing = get_missing_fields(intent)
    if missing:
        clarification = generate_clarification_message(intent, missing)
        return {
            "type": "clarification",
            "message": clarification,
            "missing_fields": missing,
            "partial_intent": intent,
        }

    # 2.5 Location prompt handling
    msg_lower = message.lower()
    loc = intent.get("location")
    loc_missing = not loc or str(loc).lower() in ["unknown", "none", "n/a", "null", ""]

    # If user replied "yes" to location prompt, ask them to fill in the fields
    if loc_missing and not intent.get("_skip_location_prompt"):
        # Check if the last assistant message was the location prompt
        last_assistant = next(
            (h for h in reversed(history) if h.get("role") == "assistant"),
            None,
        )
        user_said_yes = any(w in msg_lower for w in ["yes", "ya", "ok", "sure", "ye", "yep"])
        user_said_no = any(w in msg_lower for w in ["no", "nope", "tak", "without", "skip", "proceed", "nevermind"])

        if last_assistant and "origin and destination" in last_assistant.get("content", ""):
            if user_said_yes:
                # Ask user to input origin and destination explicitly
                return {
                    "type": "location_input",
                    "message": "Please provide your origin and destination.",
                    "partial_intent": intent,
                }
            elif user_said_no or "proceed without" in msg_lower:
                intent["_skip_location_prompt"] = True
            # else: fall through and ask the location prompt again

        if loc_missing and not intent.get("_skip_location_prompt"):
            return {
                "type": "location_prompt",
                "message": "Would you like to put your origin and destination so I can predict the Grab price, nearest public transport, and estimate travel time and cost?",
                "partial_intent": intent,
            }

    # 3. Weather
    weather_data = weather_agent.get_weather(
        date=intent.get("date") or "Unknown",
        location=intent.get("location") or "Kuala Lumpur",
    )

    # 4. Traffic
    traffic_data = traffic_agent.get_traffic(
        origin=intent.get("origin") or "current location",
        destination=intent.get("location") or "Kuala Lumpur",
        departure_time=intent.get("time") or "09:00",
    )

    # 4.5. Conflict check against existing tasks
    req_start = intent.get("time") or "09:00"
    dur_h = intent.get("duration_hours") or 1
    total_end_mins = int(req_start[:2]) * 60 + int(req_start[3:5]) + int(float(dur_h) * 60)
    req_end = f"{min(total_end_mins // 60, 23):02d}:{total_end_mins % 60:02d}"
    existing_conflicts = get_conflicts_for_slot(
        user_id, intent.get("date") or "Unknown", req_start, req_end
    )
    conflict_summary = (
        "Conflicts with existing tasks: " +
        ", ".join(f"{c['title']} ({c['start_time']}–{c.get('end_time','')})" for c in existing_conflicts)
        if existing_conflicts else "None"
    )

    # 5. Constraint check
    constraint_result = check_constraints(user_id, intent)

    # 7. Build system prompt
    custom_rules = constraint_result.get("custom_rules", [])
    custom_section = ""
    if custom_rules:
        rules_text = "\n".join(f"- {r}" for r in custom_rules)
        custom_section = f"Additional user rules (append to context):\n{rules_text}"

    restrictions_summary = (
        "; ".join(constraint_result["violations"])
        if constraint_result["violations"]
        else "None"
    )

    def _safe(val: str) -> str:
        """Escape curly braces so .format() doesn't misinterpret them."""
        return str(val).replace("{", "{{").replace("}", "}}")

    system_prompt = GLM_SYSTEM_PROMPT_TEMPLATE.format(
        task_name            = _safe(intent.get("task_name") or "Unknown"),
        date                 = _safe(intent.get("date") or "Unknown"),
        time                 = _safe(intent.get("time") or "Flexible"),
        duration_hours       = intent.get("duration_hours") or 1,
        location             = _safe(intent.get("location") or "Not specified"),
        weather_summary      = _safe(weather_data["summary"]),
        traffic_summary      = _safe(traffic_data["summary"]) + f" | Calendar conflicts: {_safe(conflict_summary)}",
        restrictions_summary = _safe(restrictions_summary),
        priority             = priority,
        custom_rules_section = _safe(custom_section),
    )

    # 8. Build message history for GLM
    glm_messages = history + [{"role": "user", "content": message}]

    # 9. Call GLM
    raw = call_glm(glm_messages, system_prompt, intent, weather_data, traffic_data)

    # 10. Parse GLM response
    import json
    parsed = {"explanation": "I'm sorry, I couldn't process that properly.", "suggestion": None, "alternatives": []}
    if raw:
        try:
            parsed = _repair_json(raw)
        except Exception:
            parsed = {"explanation": raw, "suggestion": None, "alternatives": []}

    return {
        "type":              "suggestion",
        "intent":            intent,
        "weather":           weather_data,
        "traffic":           traffic_data,
        "constraints":       constraint_result,
        "priority":          priority,
        "glm_raw":           raw,
        "parsed":            parsed,
        "calendar_conflicts": existing_conflicts,   # list of conflicting tasks
    }
