"""
Orchestrator agent — full pipeline:
  user message → intent parse → weather → traffic → constraint check
  → priority score → GLM system prompt → call GLM → return response
"""

import re
from datetime import datetime, timedelta
from agents import weather as weather_agent
from agents import traffic as traffic_agent
from models.schedule_store import get_restrictions
from config import ZAI_BASE_URL, ZAI_MODEL, ZAI_API_KEY
import requests

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
        # Named day
        for day_name, day_num in DAYS.items():
            if day_name in msg:
                days_ahead = (day_num - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                if "next" in msg:
                    days_ahead += 7
                intent["date"] = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                break

        # ISO date pattern YYYY-MM-DD
        iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", msg)
        if iso:
            intent["date"] = iso.group(1)

        # DD/MM or D Month
        dm = re.search(r"\b(\d{1,2})[/\-](\d{1,2})\b", msg)
        if dm and not intent["date"]:
            try:
                d = int(dm.group(1)); mo = int(dm.group(2))
                intent["date"] = today.replace(month=mo, day=d).strftime("%Y-%m-%d")
            except ValueError:
                pass

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
    loc = re.search(r"(?:at|in|@|di)\s+([A-Za-z][A-Za-z\s]{2,30}?)(?:\s+at|\s+on|$|,|\.|!)", message)
    if loc:
        intent["location"] = loc.group(1).strip()

    return intent


def get_missing_fields(intent: dict) -> list:
    """Return list of required fields that are still None."""
    return [f for f in REQUIRED_FIELDS if not intent.get(f)]


def build_clarification_message(missing: list) -> str:
    """Build a friendly question asking for the first missing field."""
    field = missing[0]
    return CLARIFICATION_PROMPTS[field]


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
                        if block_start <= req_time <= block_end:
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
# Priority scorer
# ─────────────────────────────────────────────────────────────────────────────

HIGH_PRIORITY_KEYWORDS = [
    "urgent", "important", "deadline", "exam", "interview", "meeting",
    "doctor", "hospital", "emergency", "mendesak", "penting",
]


def score_priority(intent: dict, message: str) -> int:
    """Assign urgency score 1–10."""
    score = 5
    msg_lower = message.lower()

    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in msg_lower:
            score = min(score + 2, 10)

    # Same-day tasks get higher priority
    today = datetime.now().strftime("%Y-%m-%d")
    if intent.get("date") == today:
        score = min(score + 1, 10)

    return score


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
Crucially, you MUST provide a detailed Transport Rationale:
1. If the weather is bad (heavy rain) or traffic is crowded, actively advise the user to take Public Transport (LRT, MRT, BRT, etc.) instead of a car or Grab.
2. Estimate the money saved. (For example, Grab might cost RM35, while public transit costs RM3. Say: "By taking public transit instead of Grab, you can save roughly RM32.")
3. In the UI, this rationale will be shown fully. Make it polite and helpful.

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


def call_glm(messages: list, system_prompt: str, intent: dict = None) -> str:
    """Call Z.AI GLM and return the response text."""
    if not ZAI_API_KEY:
        return _mock_glm_response(messages, intent)

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
    resp = requests.post(
        f"{ZAI_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _mock_glm_response(messages: list, intent: dict = None) -> str:
    """Return a mock GLM response when no API key is set (for development)."""
    import json
    today = datetime.now()
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    req_time = intent.get("time") if intent and intent.get("time") else "14:00"
    req_date = intent.get("date") if intent and intent.get("date") else tomorrow
    task_name = intent.get("task_name") if intent and intent.get("task_name") else "Scheduled Task"
    
    # Calculate a 1 hour prior departure time
    try:
        hr = int(req_time.split(":")[0])
        depart_hr = hr - 1
        departure_time = f"{depart_hr}:00"
        # 12hr format for text
        depart_12 = f"{depart_hr if depart_hr <= 12 else depart_hr - 12} {'AM' if depart_hr < 12 else 'PM'}"
        req_12 = f"{hr if hr <= 12 else hr - 12} {'AM' if hr < 12 else 'PM'}"
        
        end_time = f"{hr + 1}:00" if hr + 1 < 24 else "23:59"
    except:
        departure_time = "14:00"
        depart_12 = "2 PM"
        req_12 = "3 PM"
        end_time = "16:00"

    return json.dumps({
        "suggestion": {
            "title": task_name,
            "date": req_date,
            "start_time": req_time,
            "end_time": end_time,
            "location": intent.get("location", "Kuala Lumpur") if intent else "Kuala Lumpur",
            "status": "confirmed",
            "notes": "Mock response — set ZAI_API_KEY for live GLM responses.",
            "rationale": f"The weather forecast indicates heavy rain, and traffic is extremely crowded from your location. We strongly recommend you leave at **{depart_12}** and use the **BRT/LRT (Public Transport)** instead of taking a Grab to arrive on time for your {task_name}. Given average surge pricing, taking transit will save you approximately **RM 32**.",
            "savings_rm": 32
        },
        "explanation": (
            f"I scheduled '{task_name}' for {req_12}. Since it will be raining heavily, I suggest leaving at {depart_12} and taking the BRT/LRT which saves you RM32!"
        ),
        "alternatives": [
            {"date": req_date, "start_time": departure_time, "end_time": req_time},
        ],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run(user_id: int, message: str, history: list) -> dict:
    """
    Full orchestration pipeline.
    Returns a dict with keys: type, payload, clarification_needed, missing_fields
    """
    # 0. Contextual mapping of previously captured intent
    # If the user is just answering a clarification, we need to merge with what they asked before!
    # A simple but robust heuristic: if we are in a clarification, merge the parsed result with the prior partial intent.
    partial_intent = None
    if history and history[-1].get("role") == "assistant" and "partial_intent" in history[-1]:
        # We didn't persist partial_intent in the UI history easily, 
        # so let's rely on the chat parsing all the history dynamically!
        pass

    # A better approach given the architecture: parse the whole history to rebuild the intent!
    intent = {
        "task_name": None,
        "date": None,
        "time": None,
        "duration_hours": 1,
        "location": None,
    }
    
    # Run through history chronologically to build up the intent
    for h in history:
        if h["role"] == "user":
            step_intent = parse_intent(h["content"])
            for k in ["task_name", "date", "time", "location"]:
                if hasattr(step_intent, 'get') and step_intent.get(k):
                    intent[k] = step_intent[k]
                    
    # Parse the current message with history context
    current_intent = parse_intent(message, history)
    for k in ["task_name", "date", "time", "location"]:
        if current_intent.get(k):
            intent[k] = current_intent[k]

    # 2. Check for missing required fields — ask user instead of guessing
    missing = get_missing_fields(intent)
    if missing:
        clarification = build_clarification_message(missing)
        return {
            "type": "clarification",
            "message": clarification,
            "missing_fields": missing,
            "partial_intent": intent,
        }

    # 3. Weather
    weather_data = weather_agent.get_weather(
        date=intent["date"],
        location=intent.get("location", "Kuala Lumpur"),
    )

    # 4. Traffic
    traffic_data = traffic_agent.get_traffic(
        origin="current location",
        destination=intent.get("location", "Kuala Lumpur"),
        departure_time=intent.get("time", "09:00"),
    )

    # 5. Constraint check
    constraint_result = check_constraints(user_id, intent)

    # 6. Priority score
    priority = score_priority(intent, message)

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

    system_prompt = GLM_SYSTEM_PROMPT_TEMPLATE.format(
        task_name         = intent.get("task_name", "Unknown"),
        date              = intent.get("date", "Unknown"),
        time              = intent.get("time", "Flexible"),
        duration_hours    = intent.get("duration_hours", 1),
        location          = intent.get("location", "Not specified"),
        weather_summary   = weather_data["summary"],
        traffic_summary   = traffic_data["summary"],
        restrictions_summary = restrictions_summary,
        priority          = priority,
        custom_rules_section = custom_section,
    )

    # 8. Build message history for GLM
    glm_messages = history + [{"role": "user", "content": message}]

    # 9. Call GLM
    raw = call_glm(glm_messages, system_prompt, intent)

    # 10. Parse GLM response
    import json
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"explanation": raw, "suggestion": None, "alternatives": []}

    # Determine final status
    if constraint_result["status"] == "blocked":
        if parsed.get("suggestion"):
            parsed["suggestion"]["status"] = "blocked"
    elif not weather_data["suitable_outdoor"] or traffic_data["peak_hour_warning"]:
        if parsed.get("suggestion"):
            parsed["suggestion"]["status"] = "warning"

    return {
        "type": "suggestion",
        "intent": intent,
        "weather": weather_data,
        "traffic": traffic_data,
        "constraints": constraint_result,
        "priority": priority,
        "glm_raw": raw,
        "parsed": parsed,
    }
