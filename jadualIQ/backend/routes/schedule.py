"""Schedule CRUD routes."""
from flask import Blueprint, request, jsonify, session
from models.schedule_store import get_tasks, add_task, update_task, delete_task

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
    task = add_task(user_id, data)
    return jsonify(task), 201


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
