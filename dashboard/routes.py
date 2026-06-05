#!/usr/bin/env python3
"""
WQ Dashboard - API 路由层
=========================
从 server.py 提取的 16 个 API 端点实现。
依赖 data_access (数据读取) 和 business (业务逻辑)。
"""
from flask import Flask, jsonify, request

# Use absolute imports for direct execution, relative for module mode
try:
    import data_access as da
    import business as b
except ImportError:
    from . import data_access as da
    from . import business as b


def register_routes(app: Flask) -> None:
    """将所有路由注册到 Flask app。"""

    # ─── 1. /api/status — 完整状态 (向后兼容) ────────────────────

    @app.route("/api/status")
    def api_status():
        return jsonify(b._get_status_data())

    # ─── 2. /api/poll — 单接口轮询 (全部数据) ─────────────────────

    @app.route("/api/poll")
    def api_poll():
        data = b._get_status_data()
        return jsonify(b.build_poll_data(data))

    # ─── 3. /api/actives — 已激活 Alpha 列表 ──────────────────────

    @app.route("/api/actives")
    def api_actives():
        full_state = da.load_workflow_state("workflow")
        if not full_state:
            full_state = da.read_json_safe(da.STATE_FILE)
        actives = full_state.get("actives_data", [])
        return jsonify(b.build_actives_summary(actives))

    # ─── 4. /api/batch — 当前批次详情 ─────────────────────────────

    @app.route("/api/batch")
    def api_batch():
        full_state = da.load_workflow_state("workflow")
        if not full_state:
            full_state = da.read_json_safe(da.STATE_FILE)
        batch_state = da.load_batch_state()
        return jsonify(b.build_batch_details(
            batch=full_state.get("current_batch", []),
            batch_idx=full_state.get("batch_idx", 0),
            batch_state=batch_state,
        ))

    # ─── 5. /api/orthogonality — 正交性图 ─────────────────────────

    @app.route("/api/orthogonality")
    def api_orthogonality():
        full_state = da.load_workflow_state("workflow")
        if not full_state:
            full_state = da.read_json_safe(da.STATE_FILE)
        actives = full_state.get("actives_data", [])
        return jsonify(b.build_orthogonality_data(actives))

    # ─── 6. /api/history — Alpha 历史事件 ─────────────────────────

    @app.route("/api/history")
    def api_history():
        # Primary: SQLite
        try:
            result = da.get_alpha_history_flat(limit=200)
            if result[0].get("total", 0) > 0:
                return jsonify(result[0])
        except Exception as e:
            print(f"SQLite history error: {e}", flush=True)

        # Fallback: parse log file
        log_text = ""
        try:
            if da.LOG_FILE.exists():
                log_text = da.LOG_FILE.read_text()
        except Exception:
            pass

        history = da.parse_log_text_for_history(log_text)
        return jsonify({"total": len(history), "events": history})

    # ─── 7. /api/events — Alpha 生命周期事件 ──────────────────────

    @app.route("/api/events")
    def api_events():
        limit = request.args.get("limit", 100, type=int)
        events, err = da.get_recent_alpha_events(limit=limit)
        if err:
            return jsonify({"error": err}), 500
        return jsonify({"total": limit, "events": events})

    # ─── 8. /api/cumulative — 累计统计 ────────────────────────────

    @app.route("/api/cumulative")
    def api_cumulative():
        stats = da.get_cumulative_stats()
        if stats is None:
            return jsonify({"error": "cumulative stats unavailable"}), 500
        return jsonify(stats)

    # ─── 9. /api/log — 日志 ───────────────────────────────────────

    @app.route("/api/log")
    def api_log():
        n = request.args.get("lines", 100, type=int)
        log_entries, source = da.get_log_lines(n=n)
        return jsonify({
            "total": len(log_entries),
            "returned": len(log_entries),
            "entries": log_entries,
            "source": source,
        })

    # ─── 10. /api/logs/errors — 错误日志 ──────────────────────────

    @app.route("/api/logs/errors")
    def api_errors():
        errors, err = da.get_error_lines(limit=100)
        if err:
            return jsonify({"error": errors}), 500
        return jsonify({"total": len(errors), "entries": errors})

    # ─── 11. /api/logs/warnings — 警告日志 ────────────────────────

    @app.route("/api/logs/warnings")
    def api_warnings():
        warns, err = da.get_warning_lines(limit=100)
        if err:
            return jsonify({"error": warns}), 500
        return jsonify({"total": len(warns), "entries": warns})

    # ─── 12. /api/alphas/history — Alpha 历史记录 ──────────────────

    @app.route("/api/alphas/history")
    def api_alphas_history():
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        data, err = da.get_alpha_history_flat(limit=limit, offset=offset)
        if err:
            return jsonify({"error": err}), 500
        # Rename "events" key to "alphas" for frontend compat
        return jsonify({
            "total": data.get("total", 0),
            "alphas": data.get("events", []),
        })

    # ─── 13. /api/alphas/submitted — 已提交 Alpha ──────────────────

    @app.route("/api/alphas/submitted")
    def api_alphas_submitted():
        alphas, err = da.get_submitted_alphas()
        if err:
            return jsonify({"error": err}), 500
        return jsonify({"total": len(alphas), "alphas": alphas})

    # ─── 14. /api/alphas/complete — Alpha 完整生命周期 ─────────────

    @app.route("/api/alphas/complete")
    def api_alphas_complete():
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        result, err = da.get_all_alphas_summary(limit=limit, offset=offset)
        if err:
            return jsonify({"error": err}), 500
        return jsonify(result)

    # ─── 15. /api/improvements — 自我进化改进记录 ───────────────────

    @app.route("/api/improvements")
    def api_improvements():
        improvements, err = da.get_improvements(limit=50)
        if err:
            return jsonify({"error": improvements}), 500
        return jsonify(improvements)

    # ─── 16. / — 根端点 (向后兼容) ────────────────────────────────

    @app.route("/")
    def index():
        return jsonify({
            "name": "wq-alpha-pipeline",
            "api": "/api/status",
            "frontend": "http://localhost:8766",
            "docs": "https://github.com/Shulaolao/wq-alpha-pipeline",
        })
