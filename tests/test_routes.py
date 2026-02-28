import unittest
from contextlib import ExitStack
from io import BytesIO
from datetime import datetime
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

import app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch("app.ensure_tables_initialized", return_value=None))
        self.stack.enter_context(patch("auth_routes.ensure_tables_initialized", return_value=None))
        self.stack.enter_context(patch("app_routes.ensure_tables_initialized", return_value=None))
        self.stack.enter_context(patch("reminder_routes.ensure_tables_initialized", return_value=None))
        self.client = app.app.test_client()

    def tearDown(self):
        self.stack.close()

    def _login_session(self, user_id=1, username="tester"):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username

    def test_unauthenticated_access_redirects_and_blocks_api(self):
        page = self.client.get("/dashboard")
        api_call = self.client.get("/api/subjects")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/login", page.location)
        self.assertEqual(api_call.status_code, 401)

    def test_login_success_sets_session(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = {
            "id": 7,
            "username": "alice",
            "password_hash": generate_password_hash("secret12"),
        }

        with patch("auth_routes.get_db_connection", return_value=conn):
            response = self.client.post(
                "/login",
                json={"username": "alice", "password": "secret12"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        me = self.client.get("/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["username"], "alice")

    def test_login_invalid_credentials_returns_401(self):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchone.return_value = None

        with patch("auth_routes.get_db_connection", return_value=conn):
            response = self.client.post(
                "/login",
                json={"username": "missing", "password": "wrong"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid credentials", response.get_json()["message"])

    def test_subjects_list_uses_current_user_scope(self):
        self._login_session(user_id=42, username="bob")
        conn = MagicMock()
        expected = [
            {
                "id": 1,
                "userId": 42,
                "name": "Operating Systems",
                "semester": "Sem 5",
                "proficiencyLevel": 0,
                "createdAt": None,
                "topics": [],
            }
        ]

        with patch("app_routes.get_db_connection", return_value=conn), patch(
            "app_routes.fetch_subjects_with_topics", return_value=expected
        ) as fetch_mock:
            response = self.client.get("/api/subjects")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        fetch_mock.assert_called_once_with(conn, 42)

    def test_new_chat_inserts_with_logged_in_user_id(self):
        self._login_session(user_id=55, username="sam")
        conn = MagicMock()
        cur = MagicMock()
        cur.lastrowid = 999
        conn.cursor.return_value = cur

        with patch("app_routes.get_db_connection", return_value=conn):
            response = self.client.post("/new_chat")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["chat_id"], 999)
        cur.execute.assert_called_with(
            "INSERT INTO chats (title, user_id) VALUES (%s, %s)",
            ("New Chat", 55),
        )

    def test_create_topic_accepts_unit_id(self):
        self._login_session(user_id=5, username="sam")
        conn = MagicMock()
        cur_main = MagicMock()
        cur_fetch = MagicMock()
        conn.cursor.side_effect = [cur_main, cur_fetch]
        cur_main.fetchone.return_value = {"id": 10}
        cur_main.lastrowid = 77
        cur_fetch.fetchone.return_value = {
            "id": 77,
            "subject_id": 10,
            "unit_id": 22,
            "name": "Trees",
            "is_completed": 0,
            "confidence": 0,
        }

        with patch("app_routes.get_db_connection", return_value=conn), patch(
            "app_routes.require_owned_row", return_value=True
        ):
            response = self.client.post(
                "/api/subjects/10/topics",
                json={"name": "Trees", "unitId": 22},
            )

        self.assertEqual(response.status_code, 201)
        cur_main.execute.assert_any_call(
            "INSERT INTO topics (subject_id, unit_id, name, is_completed, confidence) VALUES (%s, %s, %s, %s, %s)",
            (10, 22, "Trees", 0, 0),
        )
        self.assertEqual(response.get_json()["unitId"], 22)

    def test_import_syllabus_returns_clear_error_when_parser_unavailable(self):
        self._login_session(user_id=5, username="sam")
        with patch(
            "app_routes._extract_pdf_text",
            side_effect=RuntimeError("PDF parsing requires `pypdf`. Install it with: pip install pypdf"),
        ):
            response = self.client.post(
                "/api/subjects/import-syllabus",
                data={
                    "name": "Operating Systems",
                    "semester": "Sem 5",
                    "syllabus": (BytesIO(b"%PDF-1.4 fake"), "os.pdf"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 500)
        self.assertIn("pypdf", response.get_json()["message"])

    def test_create_voice_reminder_success(self):
        self._login_session(user_id=3, username="planner")
        parsed = {
            "title": "Submit DSA assignment",
            "deadline_datetime": datetime(2026, 3, 2, 22, 0, 0),
            "remind_before_minutes": 60,
        }
        saved = {
            "id": 11,
            "title": "Submit DSA assignment",
            "deadline_datetime": datetime(2026, 3, 2, 22, 0, 0),
            "remind_before_minutes": 60,
            "reminder_time": datetime(2026, 3, 2, 21, 0, 0),
        }
        with patch("reminder_routes.reminder_extraction", return_value=parsed), patch(
            "reminder_routes.save_reminder", return_value=saved
        ):
            response = self.client.post(
                "/create_voice_reminder",
                json={"transcript": "Remind me to submit DSA assignment tomorrow at 10 pm"},
            )

        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["reminder"]["id"], 11)

    def test_create_voice_reminder_ambiguous_date_returns_400(self):
        self._login_session(user_id=3, username="planner")
        with patch(
            "reminder_routes.reminder_extraction",
            side_effect=ValueError("Could not confidently parse date. Please rephrase."),
        ):
            response = self.client.post(
                "/create_voice_reminder",
                json={"transcript": "Remind me sometime soon"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not confidently parse date", response.get_json()["message"])

    def test_check_notifications_returns_triggered_items(self):
        self._login_session(user_id=8, username="planner")
        mocked = [
            {
                "id": 44,
                "title": "Contest reminder",
                "description": "I have a contest on Sunday evening",
                "deadline_datetime": datetime(2026, 3, 1, 18, 0, 0),
                "reminder_time": datetime(2026, 3, 1, 17, 0, 0),
            }
        ]
        with patch("reminder_routes.fetch_notifications", return_value=mocked):
            response = self.client.get("/check_notifications")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(payload["notifications"]), 1)
        self.assertEqual(payload["notifications"][0]["id"], 44)

    def test_list_reminders_returns_user_data(self):
        self._login_session(user_id=8, username="planner")
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchall.return_value = [
            {
                "id": 1,
                "title": "Contest",
                "description": "Sunday evening",
                "deadline_datetime": datetime(2026, 3, 1, 18, 0, 0),
                "remind_before_minutes": 60,
                "reminder_time": datetime(2026, 3, 1, 17, 0, 0),
                "status": "pending",
                "created_at": datetime(2026, 2, 23, 10, 0, 0),
            }
        ]
        with patch("db_utils.get_db_connection", return_value=conn):
            response = self.client.get("/api/reminders")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["reminders"]), 1)

    def test_delete_reminder_returns_204_when_found(self):
        self._login_session(user_id=8, username="planner")
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 1
        conn.cursor.return_value = cur
        with patch("db_utils.get_db_connection", return_value=conn):
            response = self.client.delete("/api/reminders/9")
        self.assertEqual(response.status_code, 204)


if __name__ == "__main__":
    unittest.main()
