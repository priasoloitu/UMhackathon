"""Impact stats route."""
from flask import Blueprint, jsonify, session
from models.schedule_store import get_impact

impact_bp = Blueprint("impact", __name__, url_prefix="/api")


@impact_bp.route("/impact", methods=["GET"])
def impact():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify(get_impact(user_id))
