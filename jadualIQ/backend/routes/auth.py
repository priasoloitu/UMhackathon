"""Auth routes — register, login, logout, current user."""
from flask import Blueprint, request, jsonify, session
from models.schedule_store import create_user, verify_user

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    try:
        user = create_user(username, email, password)
    except ValueError as e:
        msg = str(e)
        if "username" in msg:
            return jsonify({"error": "Username already taken"}), 409
        if "email" in msg:
            return jsonify({"error": "Email already registered"}), 409
        return jsonify({"error": msg}), 409

    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    return jsonify({"ok": True, "user": user}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data     = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = verify_user(username, password)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    return jsonify({"ok": True, "user": user})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify({
        "id":       session["user_id"],
        "username": session["username"],
    })
