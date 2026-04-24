"""Chat route — guardrail → orchestrator → GLM → response."""
from flask import Blueprint, request, jsonify, session
from agents import orchestrator

chat_bp = Blueprint("chat", __name__, url_prefix="/api")


def _require_auth():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return uid, None


@chat_bp.route("/chat", methods=["POST"])
def chat():
    user_id, err = _require_auth()
    if err:
        return err

    data    = request.get_json() or {}
    message = (data.get("message") or "").strip()
    history = data.get("history", [])   # list of {role, content}

    if not message:
        return jsonify({"error": "message is required"}), 400

    # ── Orchestrator pipeline ─────────────────────────────────────────────────
    result = orchestrator.run(
        user_id=user_id,
        message=message,
        history=history,
    )

    return jsonify(result)
