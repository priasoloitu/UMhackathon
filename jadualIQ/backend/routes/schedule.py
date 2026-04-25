"""Schedule CRUD routes."""
from flask import Blueprint, request, jsonify, session
from models.schedule_store import get_tasks, add_task, update_task, delete_task, get_conflicts_for_slot

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api")


def _require_auth():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return uid, None


@schedule_bp.route("/schedule", methods=["GET"])
def list_tasks():
    user_id, err = _require_auth()
    if err:
        return err
    tasks = get_tasks(user_id)
    return jsonify(tasks)


@schedule_bp.route("/schedule", methods=["POST"])
def create_task():
    user_id, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    if not data.get("title") or not data.get("date") or not data.get("start_time"):
        return jsonify({"error": "title, date and start_time are required"}), 400

    # Check for conflicts before saving
    end_time = data.get("end_time") or (
        lambda s: f"{min((int(s[:2]) * 60 + int(s[3:5]) + 60) // 60, 23):02d}:{(int(s[:2]) * 60 + int(s[3:5]) + 60) % 60:02d}"
    )(data["start_time"])
    conflicts = get_conflicts_for_slot(
        user_id, data["date"], data["start_time"], end_time
    )

    task = add_task(user_id, data, conflict_detected=len(conflicts) > 0)
    return jsonify({
        **task,
        "conflict_warning": len(conflicts) > 0,
        "conflicts": conflicts,
    }), 201


@schedule_bp.route("/schedule/<int:task_id>", methods=["PUT"])
def edit_task(task_id):
    user_id, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    task = update_task(task_id, user_id, data)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@schedule_bp.route("/schedule/<int:task_id>", methods=["DELETE"])
def remove_task(task_id):
    user_id, err = _require_auth()
    if err:
        return err
    ok = delete_task(task_id, user_id)
    if not ok:
        return jsonify({"error": "Task not found"}), 404
    return jsonify({"ok": True})
