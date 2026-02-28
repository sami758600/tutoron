import os

from push_service import send_pending_push_notifications
from reminder_service import check_due_reminders

_scheduler = None


def start_reminder_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception:
        # APScheduler is optional at runtime; routes still work without background triggers.
        return None

    debug = os.getenv("FLASK_DEBUG") == "1"
    # Avoid duplicate scheduler in Flask debug reloader.
    if debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return None

    def _tick():
        check_due_reminders()
        send_pending_push_notifications()

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_tick, "interval", seconds=60, id="reminder_tick", replace_existing=True)
    scheduler.start()
    _scheduler = scheduler
    return _scheduler
