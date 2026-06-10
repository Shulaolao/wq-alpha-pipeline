#!/usr/bin/env python3
"""
WQ Dashboard Server v4 — Modular Architecture
===============================================
入口文件: 创建 Flask app, 注册路由, 启动服务。
所有业务逻辑已拆分到 data_access.py / business.py / routes.py。

启动方式:
    python server.py          (launchd / 直接执行)
    python -m dashboard       (模块模式)
"""
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request

# Ensure our dashboard dir is on sys.path for module imports
_DASHBOARD_DIR = Path(__file__).resolve().parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

# Add scripts dir for wq_db import
_SCRIPT_DIR = Path(os.environ.get("WQ_SCRIPT_DIR", Path.home() / ".hermes" / "scripts"))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─── App creation ─────────────────────────────────────────────────

app = Flask(__name__)


# ─── CORS ─────────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    # Allow CORS for local, ngrok, and Tailscale domains
    if origin and ("localhost" in origin or "127.0.0.1" in origin or 
                   "ngrok-free.app" in origin or ".ts.net" in origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


# ─── Route registration ───────────────────────────────────────────

# Use absolute imports for direct execution (python server.py)
# When run as module (python -m dashboard), relative imports work
try:
    from routes import register_routes
except ImportError:
    from .routes import register_routes

register_routes(app)


# ─── Main entry ───────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8767))
    print(f"🚀 WQ Dashboard v4 starting on http://0.0.0.0:{port}")
    print(f"   Modules: data_access / business / routes")
    print(f"   DB:      {_SCRIPT_DIR / 'wq_db.py'}")
    app.run(host="0.0.0.0", port=port, debug=False)
