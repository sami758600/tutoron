import json
import os

from db_utils import get_db_connection


def get_vapid_public_key():
    return os.getenv("VAPID_PUBLIC_KEY", "").strip()


def push_available():
    return bool(get_vapid_public_key() and os.getenv("VAPID_PRIVATE_KEY", "").strip())


def save_subscription(user_id, subscription):
    endpoint = (subscription or {}).get("endpoint")
    if not endpoint:
        raise ValueError("Invalid subscription payload.")

    raw = json.dumps(subscription)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO push_subscriptions (user_id, endpoint, subscription_json, is_active, last_used_at)
        VALUES (%s, %s, %s, 1, NOW())
        ON DUPLICATE KEY UPDATE
            subscription_json=VALUES(subscription_json),
            is_active=1,
            last_used_at=NOW()
        """,
        (user_id, endpoint, raw),
    )
    conn.commit()
    cur.close()
    conn.close()


def remove_subscription(user_id, endpoint):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE push_subscriptions SET is_active=0 WHERE user_id=%s AND endpoint=%s",
        (user_id, endpoint),
    )
    conn.commit()
    cur.close()
    conn.close()


def _fetch_unsent_triggered():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, user_id, title, deadline_datetime
        FROM reminders
        WHERE status='triggered' AND push_sent_at IS NULL
        ORDER BY id ASC
        LIMIT 100
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _fetch_subscriptions(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, endpoint, subscription_json
        FROM push_subscriptions
        WHERE user_id=%s AND is_active=1
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _mark_subscription_inactive(sub_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE push_subscriptions SET is_active=0 WHERE id=%s", (sub_id,))
    conn.commit()
    cur.close()
    conn.close()


def _mark_push_sent(reminder_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET push_sent_at=NOW() WHERE id=%s", (reminder_id,))
    conn.commit()
    cur.close()
    conn.close()


def send_pending_push_notifications():
    if not push_available():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return 0

    vapid_private = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    vapid_email = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com").strip()
    reminders = _fetch_unsent_triggered()
    sent_count = 0

    for reminder in reminders:
        payload = json.dumps(
            {
                "title": "Tutoron Reminder",
                "body": f"{reminder['title']} (deadline: {reminder['deadline_datetime']})",
                "url": "/planning",
                "tag": f"reminder-{reminder['id']}",
            }
        )
        subscriptions = _fetch_subscriptions(reminder["user_id"])
        for sub in subscriptions:
            try:
                webpush(
                    subscription_info=json.loads(sub["subscription_json"]),
                    data=payload,
                    vapid_private_key=vapid_private,
                    vapid_claims={"sub": vapid_email},
                    ttl=120,
                )
                sent_count += 1
            except WebPushException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (404, 410):
                    _mark_subscription_inactive(sub["id"])
            except Exception:
                # Skip faulty subscription without interrupting the scheduler.
                continue
        _mark_push_sent(reminder["id"])
    return sent_count
