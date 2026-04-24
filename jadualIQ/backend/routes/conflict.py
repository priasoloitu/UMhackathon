"""Conflict detection & AI resolution routes."""
from flask import Blueprint, request, jsonify, session
from agents import orchestrator

conflict_bp = Blueprint("conflict", __name__, url_prefix="/api")


def _require_auth():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return uid, None


@conflict_bp.route("/conflicts/resolve", methods=["POST"])
def resolve():
    """POST { task_a_id, task_b_id } → AI resolution suggestion."""
    user_id, err = _require_auth()
    if err:
        return err

    data      = request.get_json() or {}
    task_a_id = data.get("task_a_id")
    task_b_id = data.get("task_b_id")

    if not task_a_id or not task_b_id:
        return jsonify({"error": "task_a_id and task_b_id are required"}), 400

    result = orchestrator.resolve_conflict(user_id, int(task_a_id), int(task_b_id))
    if not result:
        return jsonify({"error": "Tasks not found or do not belong to this user"}), 404

    return jsonify(result)
