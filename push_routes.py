from flask import jsonify, request

from auth_utils import get_current_user_id, login_required_api
from db_utils import ensure_tables_initialized
from push_service import get_vapid_public_key, push_available, remove_subscription, save_subscription


def register_push_routes(app):
    @app.route("/api/push/public-key", methods=["GET"])
    @login_required_api
    def push_public_key():
        ensure_tables_initialized()
        key = get_vapid_public_key()
        if not key:
            return jsonify({"status": "unavailable", "message": "Push key is not configured."}), 503
        return jsonify({"status": "success", "publicKey": key})

    @app.route("/api/push/subscribe", methods=["POST"])
    @login_required_api
    def push_subscribe():
        ensure_tables_initialized()
        body = request.get_json() or {}
        subscription = body.get("subscription")
        try:
            save_subscription(get_current_user_id(), subscription)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Failed to save subscription: {str(exc)}"}), 500
        return jsonify({"status": "success", "pushEnabled": push_available()})

    @app.route("/api/push/unsubscribe", methods=["POST"])
    @login_required_api
    def push_unsubscribe():
        ensure_tables_initialized()
        body = request.get_json() or {}
        endpoint = (body.get("endpoint") or "").strip()
        if not endpoint:
            return jsonify({"status": "error", "message": "endpoint is required"}), 400
        try:
            remove_subscription(get_current_user_id(), endpoint)
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Failed to unsubscribe: {str(exc)}"}), 500
        return jsonify({"status": "success"})
