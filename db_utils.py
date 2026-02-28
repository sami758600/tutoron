from datetime import date, datetime
import os

import mysql.connector

_db_initialized = False


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def _column_exists(conn, table_name, column_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (os.getenv("DB_NAME"), table_name, column_name),
    )
    exists = cur.fetchone()[0] > 0
    cur.close()
    return exists


def _index_exists(conn, table_name, index_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s
        """,
        (os.getenv("DB_NAME"), table_name, index_name),
    )
    exists = cur.fetchone()[0] > 0
    cur.close()
    return exists


def _fk_exists(conn, table_name, constraint_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_TYPE='FOREIGN KEY' AND CONSTRAINT_NAME=%s
        """,
        (os.getenv("DB_NAME"), table_name, constraint_name),
    )
    exists = cur.fetchone()[0] > 0
    cur.close()
    return exists


def ensure_tables_initialized():
    global _db_initialized
    if _db_initialized:
        return

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(80) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    if not _column_exists(conn, "chats", "user_id"):
        cur.execute("ALTER TABLE chats ADD COLUMN user_id INT NULL")
        cur.execute("CREATE INDEX idx_chats_user_id ON chats(user_id)")
        cur.execute(
            "ALTER TABLE chats ADD CONSTRAINT fk_chats_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            chat_id INT NOT NULL,
            role VARCHAR(50) NOT NULL,
            content LONGTEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subjects (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            semester VARCHAR(100) NOT NULL,
            proficiency_level INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS topics (
            id INT AUTO_INCREMENT PRIMARY KEY,
            subject_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            is_completed TINYINT(1) DEFAULT 0,
            confidence INT DEFAULT 0,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS units (
            id INT AUTO_INCREMENT PRIMARY KEY,
            subject_id INT NOT NULL,
            unit_no VARCHAR(32) NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
        """
    )

    if not _column_exists(conn, "topics", "unit_id"):
        cur.execute("ALTER TABLE topics ADD COLUMN unit_id INT NULL")

    if not _index_exists(conn, "topics", "idx_topics_unit_id"):
        cur.execute("CREATE INDEX idx_topics_unit_id ON topics(unit_id)")

    if not _fk_exists(conn, "topics", "fk_topics_unit"):
        cur.execute(
            "ALTER TABLE topics ADD CONSTRAINT fk_topics_unit FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE SET NULL"
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            category VARCHAR(100) NOT NULL,
            proficiency_level INT DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            company VARCHAR(255) NOT NULL,
            role VARCHAR(255) NOT NULL,
            status VARCHAR(100) NOT NULL,
            applied_date DATETIME NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS study_plans (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NULL,
            target_date DATETIME NULL,
            is_completed TINYINT(1) DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NULL,
            deadline_datetime DATETIME NOT NULL,
            remind_before_minutes INT NOT NULL DEFAULT 60,
            reminder_time DATETIME NOT NULL,
            status ENUM('pending', 'triggered') NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            delivered_at DATETIME NULL,
            push_sent_at DATETIME NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    if not _index_exists(conn, "reminders", "idx_reminders_due"):
        cur.execute("CREATE INDEX idx_reminders_due ON reminders(status, reminder_time)")

    if not _index_exists(conn, "reminders", "idx_reminders_user_delivered"):
        cur.execute("CREATE INDEX idx_reminders_user_delivered ON reminders(user_id, status, delivered_at)")

    if not _column_exists(conn, "reminders", "push_sent_at"):
        cur.execute("ALTER TABLE reminders ADD COLUMN push_sent_at DATETIME NULL")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            endpoint VARCHAR(512) NOT NULL,
            subscription_json LONGTEXT NOT NULL,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at DATETIME NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE KEY uk_push_user_endpoint (user_id, endpoint)
        )
        """
    )

    conn.commit()
    cur.close()
    conn.close()
    _db_initialized = True


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def to_iso(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def subject_to_api(row):
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "name": row["name"],
        "semester": row["semester"],
        "proficiencyLevel": row["proficiency_level"] or 0,
        "createdAt": to_iso(row.get("created_at")),
    }


def topic_to_api(row):
    return {
        "id": row["id"],
        "subjectId": row["subject_id"],
        "unitId": row.get("unit_id"),
        "name": row["name"],
        "isCompleted": bool(row["is_completed"]),
        "confidence": row["confidence"] or 0,
    }


def unit_to_api(row):
    return {
        "id": row["id"],
        "subjectId": row["subject_id"],
        "unitNo": row.get("unit_no"),
        "name": row["name"],
        "description": row.get("description"),
        "createdAt": to_iso(row.get("created_at")),
    }


def skill_to_api(row):
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "name": row["name"],
        "category": row["category"],
        "proficiencyLevel": row["proficiency_level"] or 0,
    }


def application_to_api(row):
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "company": row["company"],
        "role": row["role"],
        "status": row["status"],
        "appliedDate": to_iso(row.get("applied_date")),
    }


def study_plan_to_api(row):
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "title": row["title"],
        "description": row["description"],
        "targetDate": to_iso(row.get("target_date")),
        "isCompleted": bool(row["is_completed"]),
    }


def fetch_subjects_with_topics(conn, user_id):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, user_id, name, semester, proficiency_level, created_at FROM subjects WHERE user_id=%s ORDER BY id DESC",
        (user_id,),
    )
    subjects = cur.fetchall()
    ids = [s["id"] for s in subjects]
    topics_by_subject = {sid: [] for sid in ids}
    units_by_subject = {sid: [] for sid in ids}
    units_map = {}
    if ids:
        cur.execute(
            f"SELECT id, subject_id, unit_no, name, description, created_at FROM units WHERE subject_id IN ({','.join(['%s']*len(ids))}) ORDER BY id ASC",
            tuple(ids),
        )
        for u in cur.fetchall():
            unit_api = {**unit_to_api(u), "topics": []}
            units_by_subject[u["subject_id"]].append(unit_api)
            units_map[u["id"]] = unit_api

        cur.execute(
            f"SELECT id, subject_id, unit_id, name, is_completed, confidence FROM topics WHERE subject_id IN ({','.join(['%s']*len(ids))}) ORDER BY id ASC",
            tuple(ids),
        )
        for t in cur.fetchall():
            topic_api = topic_to_api(t)
            topics_by_subject[t["subject_id"]].append(topic_api)
            if t.get("unit_id") in units_map:
                units_map[t["unit_id"]]["topics"].append(topic_api)
    cur.close()
    return [
        {
            **subject_to_api(s),
            "topics": topics_by_subject.get(s["id"], []),
            "units": units_by_subject.get(s["id"], []),
        }
        for s in subjects
    ]


def require_owned_row(cur, table, row_id, user_id):
    cur.execute(f"SELECT id FROM {table} WHERE id=%s AND user_id=%s", (row_id, user_id))
    return cur.fetchone() is not None
