"""Flask application entry point."""
import sys
import os

# ensure backend/ is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask
from flask_cors import CORS
from config import SECRET_KEY, DEBUG
from models.schedule_store import init_db
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.schedule import schedule_bp
from routes.restrictions import restrictions_bp
from routes.impact import impact_bp


def create_app():
    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    app.secret_key = SECRET_KEY

    CORS(app, supports_credentials=True, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(restrictions_bp)
    app.register_blueprint(impact_bp)

    # Serve frontend
    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    @app.route("/login")
    def login_page():
        return app.send_static_file("login.html")

    @app.route("/register")
    def register_page():
        return app.send_static_file("login.html")

    return app


if __name__ == "__main__":
    init_db()
    app = create_app()
    app.run(debug=DEBUG, port=5000)
