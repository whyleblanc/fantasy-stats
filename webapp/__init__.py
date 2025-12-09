# webapp/__init__.py

import os
from flask import Flask, send_from_directory, abort
from flask_cors import CORS

from db import init_db
from .config import Config
from .routes.meta import meta_bp
from .routes.league import league_bp
from .routes.analysis import analysis_bp
from .routes.debug import debug_bp
from .routes.legacy import legacy_bp


def _resolve_static_folder() -> str:
    """
    Point Flask at the React build output: frontend/dist
    """
    here = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(here, "..", "frontend", "dist"))


def create_app() -> Flask:
    # static_url_path="/" so "/" serves index.html nicely
    app = Flask(
        "webapp",
        static_folder=_resolve_static_folder(),
        static_url_path="/",
    )

    # Core config
    app.config.from_object(Config)

    # CORS: allow dev frontend (5173) to hit /api/* on 5001
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Init DB (tables etc.)
    init_db()

    # Register blueprints
    app.register_blueprint(meta_bp)
    app.register_blueprint(league_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(debug_bp)
    app.register_blueprint(legacy_bp)

    # ---------- React SPA routes (prod build) ----------

    @app.route("/")
    def react_index():
        """
        Serve the built React app (frontend/dist/index.html).
        """
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/<path:path>")
    def react_app(path: str):
        """
        For any non-API path, serve index.html and let React Router handle it.
        """
        if path.startswith("api/"):
            abort(404)
        # Try to serve static file first (js/css/assets)
        full_path = os.path.join(app.static_folder, path)
        if os.path.exists(full_path):
            return send_from_directory(app.static_folder, path)
        # Fallback to SPA index
        return send_from_directory(app.static_folder, "index.html")

    return app