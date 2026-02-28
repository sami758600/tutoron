from datetime import datetime

from flask import jsonify, request

from auth_utils import get_current_user_id, login_required_api
from db_utils import ensure_tables_initialized
from reminder_service import fetch_notifications, reminder_extraction, save_reminder


def register_reminder_routes(app, client):
    @app.route("/create_voice_reminder", methods=["POST"])
    @login_required_api
    def create_voice_reminder():
        ensure_tables_initialized()
        body = request.get_json() or {}
        transcript = (body.get("transcript") or "").strip()
        if not transcript:
            return jsonify({"status": "error", "message": "transcript is required"}), 400

        try:
            parsed = reminder_extraction(client, transcript)
            saved = save_reminder(get_current_user_id(), transcript, parsed)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Failed to create reminder: {str(exc)}"}), 500

        deadline = saved["deadline_datetime"]
        message = f"Reminder set for {deadline.strftime('%d %b %Y, %I:%M %p')}"
        return jsonify(
            {
                "status": "success",
                "message": message,
                "reminder": {
                    "id": saved["id"],
                    "title": saved["title"],
                    "deadlineDatetime": deadline.strftime("%Y-%m-%d %H:%M:%S"),
                    "remindBeforeMinutes": saved["remind_before_minutes"],
                    "reminderTime": saved["reminder_time"].strftime("%Y-%m-%d %H:%M:%S"),
                },
            }
        ), 201

    @app.route("/check_notifications", methods=["GET"])
    @login_required_api
    def check_notifications():
        ensure_tables_initialized()
        try:
            rows = fetch_notifications(get_current_user_id())
        except Exception as exc:
            return jsonify({"status": "error", "message": str(exc)}), 500

        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "description": r["description"],
                    "deadlineDatetime": r["deadline_datetime"].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(r["deadline_datetime"], datetime)
                    else str(r["deadline_datetime"]),
                    "reminderTime": r["reminder_time"].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(r["reminder_time"], datetime)
                    else str(r["reminder_time"]),
                }
            )
        return jsonify({"status": "success", "notifications": out})

    @app.route("/api/reminders", methods=["GET"])
    @login_required_api
    def list_reminders():
        ensure_tables_initialized()
        from db_utils import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id, title, description, deadline_datetime, remind_before_minutes, reminder_time, status, created_at
            FROM reminders
            WHERE user_id=%s
            ORDER BY reminder_time ASC
            """,
            (get_current_user_id(),),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        reminders = []
        for r in rows:
            reminders.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "description": r["description"],
                    "deadlineDatetime": r["deadline_datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                    "remindBeforeMinutes": r["remind_before_minutes"],
                    "reminderTime": r["reminder_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "status": r["status"],
                    "createdAt": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else None,
                }
            )
        return jsonify({"status": "success", "reminders": reminders})

    @app.route("/api/reminders/<int:reminder_id>", methods=["DELETE"])
    @login_required_api
    def delete_reminder(reminder_id):
        ensure_tables_initialized()
        from db_utils import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM reminders WHERE id=%s AND user_id=%s",
            (reminder_id, get_current_user_id()),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if not deleted:
            return jsonify({"status": "error", "message": "Reminder not found"}), 404
        return ("", 204)
