"""Restrictions CRUD routes."""
from flask import Blueprint, request, jsonify, session
from models.schedule_store import get_restrictions, add_restriction, delete_restriction

restrictions_bp = Blueprint("restrictions", __name__, url_prefix="/api")


def _require_auth():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return uid, None


@restrictions_bp.route("/restrictions", methods=["GET"])
def list_restrictions():
    user_id, err = _require_auth()
    if err:
        return err
    return jsonify(get_restrictions(user_id))


@restrictions_bp.route("/restrictions", methods=["POST"])
def create_restriction():
    user_id, err = _require_auth()
    if err:
        return err
    data = request.get_json() or {}
    if not data.get("type") or not data.get("value"):
        return jsonify({"error": "type and value are required"}), 400
    if not data.get("label"):
        data["label"] = data["value"]
    r = add_restriction(user_id, data)
    return jsonify(r), 201


@restrictions_bp.route("/restrictions/<int:rid>", methods=["DELETE"])
def remove_restriction(rid):
    user_id, err = _require_auth()
    if err:
        return err
    ok = delete_restriction(rid, user_id)
    if not ok:
        return jsonify({"error": "Restriction not found"}), 404
    return jsonify({"ok": True})
