import json
import re
from datetime import datetime, timedelta

from google.genai import types

from db_utils import get_db_connection


def _extract_json_block(text):
    if not text:
        return {}
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def reminder_extraction(client, transcript):
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    now_text = now_ist.strftime("%Y-%m-%d %H:%M:%S")

    prompt = """
You extract reminder details from natural language.
Return ONLY valid JSON in this format:
{
  "title": "",
  "deadline_datetime": "",
  "remind_before_minutes": 60
}

Rules:
- Convert relative dates like 'tomorrow', 'Sunday evening'
- Assume user timezone Asia/Kolkata
- If time not provided, default to 11:59 PM
- If remind_before not specified, default to 60 minutes
- Return ISO datetime format YYYY-MM-DD HH:MM:SS
- If ambiguous, return empty deadline_datetime
- No explanation text. JSON only.
""".strip()

    user_text = f"Current datetime in Asia/Kolkata: {now_text}\nTranscript: {transcript}"
    result = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=[types.Part(text=user_text)])],
        config=types.GenerateContentConfig(system_instruction=prompt, temperature=0.0),
    )
    data = _extract_json_block(result.text or "")
    title = (data.get("title") or "").strip() or "Reminder"
    deadline_text = (data.get("deadline_datetime") or "").strip()
    remind_before = int(data.get("remind_before_minutes") or 60)
    if remind_before <= 0:
        remind_before = 60

    if not deadline_text:
        raise ValueError("Could not confidently parse date. Please rephrase.")

    try:
        deadline_dt = datetime.strptime(deadline_text, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("Could not confidently parse date. Please rephrase.") from exc
    if deadline_dt <= now_ist:
        raise ValueError("Could not confidently parse date. Please rephrase.")

    return {
        "title": title,
        "deadline_datetime": deadline_dt,
        "remind_before_minutes": remind_before,
    }


def save_reminder(user_id, transcript, parsed):
    deadline = parsed["deadline_datetime"]
    remind_before = int(parsed["remind_before_minutes"])
    reminder_time = deadline - timedelta(minutes=remind_before)
    title = parsed["title"]

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # Duplicate guard: same title and reminder time window of 5 minutes.
    cur.execute(
        """
        SELECT id
        FROM reminders
        WHERE user_id=%s
          AND LOWER(title)=LOWER(%s)
          AND ABS(TIMESTAMPDIFF(MINUTE, reminder_time, %s)) <= 5
        LIMIT 1
        """,
        (user_id, title, reminder_time),
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        raise ValueError("A similar reminder already exists within 5 minutes.")

    cur.execute(
        """
        INSERT INTO reminders
        (user_id, title, description, deadline_datetime, remind_before_minutes, reminder_time, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending')
        """,
        (user_id, title, transcript, deadline, remind_before, reminder_time),
    )
    reminder_id = cur.lastrowid
    conn.commit()

    cur.execute(
        """
        SELECT id, title, description, deadline_datetime, remind_before_minutes, reminder_time, status
        FROM reminders
        WHERE id=%s AND user_id=%s
        """,
        (reminder_id, user_id),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def check_due_reminders():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM reminders WHERE status='pending' AND reminder_time <= NOW()")
    ids = [r[0] for r in cur.fetchall()]
    if ids:
        cur.execute(
            f"UPDATE reminders SET status='triggered' WHERE id IN ({','.join(['%s'] * len(ids))})",
            tuple(ids),
        )
        conn.commit()
    cur.close()
    conn.close()
    return len(ids)


def fetch_notifications(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, title, description, deadline_datetime, reminder_time
        FROM reminders
        WHERE user_id=%s AND status='triggered' AND delivered_at IS NULL
        ORDER BY reminder_time ASC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        cur.execute(
            f"UPDATE reminders SET delivered_at=NOW() WHERE id IN ({','.join(['%s'] * len(ids))})",
            tuple(ids),
        )
        conn.commit()
    cur.close()
    conn.close()
    return rows
