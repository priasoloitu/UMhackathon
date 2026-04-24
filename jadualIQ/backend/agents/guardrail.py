"""
Guardrail agent — filters non-scheduling messages before they reach GLM.
"""

SCHEDULING_KEYWORDS = [
    "schedule", "plan", "book", "appointment", "meeting", "remind",
    "task", "event", "cancel", "reschedule", "move", "when", "time",
    "busy", "free", "available", "deadline", "jadual", "masa", "tarikh",
    "hari", "minggu", "bulan", "aktiviti", "kerja", "rest", "block",
    "morning", "afternoon", "evening", "night", "pagi", "petang", "malam",
    "today", "tomorrow", "hari ini", "esok", "lusa", "next", "this week",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "isnin", "selasa", "rabu", "khamis", "jumaat", "sabtu", "ahad",
    "hour", "jam", "minit", "minute", "duration", "tempoh", "slot",
    "remind", "alert", "notification", "set", "add", "create",
    "am", "pm", "noon", "tengahari",
]

WARNING_RESPONSE = {
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


def is_scheduling_related(message: str) -> bool:
    """Return True if the message is related to scheduling."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in SCHEDULING_KEYWORDS)


def check(message: str, history: list = None) -> dict | None:
    """
    Run the guardrail check.
    Returns None if the message passes (scheduling-related).
    Returns a warning dict if the message should be blocked.
    """
    history = history or []
    
    # If the last message from the bot was a clarification, skip guardrail
    if history:
        last_msg = history[-1]
        if last_msg.get("role") == "assistant" and "What would you like to schedule?" in last_msg.get("content", ""):
            return None
        if last_msg.get("role") == "assistant" and "Which date?" in last_msg.get("content", ""):
            return None
        if last_msg.get("role") == "assistant" and "What time do you prefer?" in last_msg.get("content", ""):
            return None
        if last_msg.get("role") == "assistant" and "put your location and destination" in last_msg.get("content", ""):
            return None

    if is_scheduling_related(message) or "proceed without location" in message.lower() or "origin:" in message.lower():
        return None  # pass through
    return WARNING_RESPONSE
