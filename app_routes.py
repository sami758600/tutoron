import re

from flask import Response, jsonify, redirect, stream_with_context, request, url_for
from google.genai import types

from auth_utils import get_current_user_id, get_current_username, login_required_api, login_required_page
from db_utils import (
    application_to_api,
    ensure_tables_initialized,
    fetch_subjects_with_topics,
    get_db_connection,
    parse_datetime,
    require_owned_row,
    skill_to_api,
    study_plan_to_api,
    subject_to_api,
    topic_to_api,
    unit_to_api,
)


UNIT_HEADING_PATTERN = re.compile(
    r"^\s*(?:UNIT|MODULE)\s*[-: ]*\s*([0-9]+|[IVXLC]+)?\s*[-:.) ]*\s*(.*)\s*$",
    re.IGNORECASE,
)


def _extract_pdf_text(file_storage):
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError(
            "PDF parsing requires `pypdf`. Install it with: pip install pypdf"
        ) from exc

    reader = PdfReader(file_storage.stream)
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _normalize_topic_text(text):
    cleaned = re.sub(r"\s+", " ", (text or "").strip(" -:\t"))
    return cleaned


def _roman_to_int(value):
    if not value:
        return None
    value = value.upper()
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(value):
        if ch not in roman_map:
            return None
        curr = roman_map[ch]
        total = total - curr if curr < prev else total + curr
        prev = curr
    return total


def _normalize_for_match(text):
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def _line_matches_subject(line, subject_name):
    if not subject_name:
        return True
    line_norm = _normalize_for_match(line)
    name_norm = _normalize_for_match(subject_name)
    if not line_norm or not name_norm:
        return False
    if name_norm in line_norm:
        return True
    tokens = [t for t in name_norm.split() if len(t) >= 3]
    if not tokens:
        return False
    hit = sum(1 for t in tokens if t in line_norm)
    return hit / len(tokens) >= 0.7


def _looks_like_topic_line(line):
    if not line:
        return False
    if re.match(r"^\(?\d+[).:-]?\s+", line):
        return True
    if re.match(r"^[\-*]\s+", line):
        return True
    if ":" in line and line.lower().split(":", 1)[0].strip() in {"topics", "topic", "contents", "content"}:
        return True
    words = line.split()
    return len(words) <= 16 and len(line) <= 120


def _parse_units_and_topics(raw_text, subject_name=None):
    units = []
    current = None
    seen_topic_keys = set()
    unit_numbers = []

    lines = [ln.strip() for ln in (raw_text or "").splitlines()]
    start_idx = 0
    if subject_name:
        for idx, raw in enumerate(lines):
            if _line_matches_subject(raw, subject_name):
                start_idx = idx
                break
        else:
            return []

    for raw in lines[start_idx:]:
        line = _normalize_topic_text(raw)
        if not line:
            continue

        head = UNIT_HEADING_PATTERN.match(line)
        if head:
            unit_no = (head.group(1) or "").strip() or None
            unit_num_int = None
            if unit_no:
                unit_num_int = int(unit_no) if unit_no.isdigit() else _roman_to_int(unit_no)

            # Stop at likely next subject when numbering restarts (e.g. UNIT 1 after UNIT 5).
            if units and unit_num_int == 1 and any((x or 0) > 1 for x in unit_numbers):
                break

            unit_name = _normalize_topic_text(head.group(2)) or (f"Unit {unit_no}" if unit_no else "Unit")
            current = {"unitNo": unit_no, "name": unit_name, "topics": []}
            units.append(current)
            unit_numbers.append(unit_num_int)
            if len(units) >= 8:
                break
            continue

        if not current:
            continue

        if not _looks_like_topic_line(line):
            continue

        chunks = [c.strip() for c in re.split(r"[;,]\s*", line) if c.strip()]
        for chunk in chunks:
            topic = _normalize_topic_text(chunk)
            if len(topic) < 3 or len(topic) > 90:
                continue
            if len(topic.split()) > 14:
                continue
            key = (current["name"].lower(), topic.lower())
            if key in seen_topic_keys:
                continue
            seen_topic_keys.add(key)
            current["topics"].append(topic)

    return [u for u in units if u["topics"]]


def register_app_routes(app, client, system_prompt):
    def render_page(template, page, title):
        from flask import render_template

        return render_template(template, page=page, title=title, username=get_current_username())

    @app.route("/")
    def home():
        ensure_tables_initialized()
        if not get_current_user_id():
            return redirect(url_for("login_page"))
        return redirect(url_for("dashboard_page"))

    @app.route("/dashboard")
    @login_required_page
    def dashboard_page():
        ensure_tables_initialized()
        return render_page("dashboard.html", "dashboard", "Tutoron AI - Dashboard")

    @app.route("/academic")
    @login_required_page
    def academic_page():
        ensure_tables_initialized()
        return render_page("academic.html", "academic", "Tutoron AI - Academic")

    @app.route("/skills")
    @login_required_page
    def skills_page():
        ensure_tables_initialized()
        return render_page("skills.html", "skills", "Tutoron AI - Skills")

    @app.route("/placement")
    @login_required_page
    def placement_page():
        ensure_tables_initialized()
        return render_page("placement.html", "placement", "Tutoron AI - Placement")

    @app.route("/planning")
    @login_required_page
    def planning_page():
        ensure_tables_initialized()
        return render_page("planning.html", "planning", "Tutoron AI - Planning")

    @app.route("/tutor")
    @login_required_page
    def tutor_page():
        ensure_tables_initialized()
        return render_page("tutor.html", "tutor", "Tutoron AI - AI Tutor")

    @app.route("/new_chat", methods=["POST"])
    @login_required_api
    def new_chat():
        ensure_tables_initialized()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO chats (title, user_id) VALUES (%s, %s)", ("New Chat", get_current_user_id()))
        conn.commit()
        chat_id = cur.lastrowid
        cur.close()
        conn.close()
        return jsonify({"chat_id": chat_id})

    @app.route("/chats")
    @login_required_api
    def get_chats():
        ensure_tables_initialized()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, title FROM chats WHERE user_id=%s ORDER BY id DESC", (get_current_user_id(),))
        data = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(data)

    @app.route("/chat/<int:chat_id>")
    @login_required_api
    def load_chat(chat_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()
        cur = conn.cursor()
        if not require_owned_row(cur, "chats", chat_id, uid):
            cur.close()
            conn.close()
            return jsonify({"message": "Chat not found"}), 404
        cur.execute("SELECT role, content FROM messages WHERE chat_id=%s ORDER BY id ASC", (chat_id,))
        messages = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(messages)

    @app.route("/ask", methods=["POST"])
    @login_required_api
    def ask():
        ensure_tables_initialized()
        uid = get_current_user_id()
        data = request.get_json() or {}
        chat_id = data.get("chat_id")
        user_message = (data.get("message") or "").strip()
        if not chat_id or not user_message:
            return jsonify({"error": "Invalid request"}), 400

        conn = get_db_connection()
        own_cur = conn.cursor()
        if not require_owned_row(own_cur, "chats", chat_id, uid):
            own_cur.close()
            conn.close()
            return jsonify({"message": "Chat not found"}), 404
        own_cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT role, content FROM messages WHERE chat_id=%s ORDER BY id ASC", (chat_id,))
        history = cur.fetchall()
        contents = [types.Content(role=m["role"], parts=[types.Part(text=m["content"])]) for m in history]
        contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

        def generate():
            full_reply = ""

            def sse(text):
                norm = text.replace("\r\n", "\n").replace("\r", "\n")
                return "".join(f"data: {line}\n" for line in norm.split("\n")) + "\n"

            try:
                stream = client.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.7),
                )
                for chunk in stream:
                    if chunk.text:
                        full_reply += chunk.text
                        yield sse(chunk.text)

                title_cur = conn.cursor()
                title_cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id=%s", (chat_id,))
                if title_cur.fetchone()[0] == 0:
                    title_cur.execute("UPDATE chats SET title=%s WHERE id=%s AND user_id=%s", (user_message[:40], chat_id, uid))
                    conn.commit()
                title_cur.close()

                ins = conn.cursor()
                ins.execute("INSERT INTO messages (chat_id, role, content) VALUES (%s, %s, %s)", (chat_id, "user", user_message))
                ins.execute("INSERT INTO messages (chat_id, role, content) VALUES (%s, %s, %s)", (chat_id, "model", full_reply))
                conn.commit()
                ins.close()
            except Exception as exc:
                yield sse(f"ERROR: {str(exc)}")
            finally:
                cur.close()
                conn.close()

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    @app.route("/delete_chat/<int:chat_id>", methods=["POST"])
    @login_required_api
    def delete_chat(chat_id):
        ensure_tables_initialized()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM chats WHERE id=%s AND user_id=%s", (chat_id, get_current_user_id()))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "deleted"})

    @app.route("/rename_chat/<int:chat_id>", methods=["POST"])
    @login_required_api
    def rename_chat(chat_id):
        ensure_tables_initialized()
        title = (request.get_json() or {}).get("title", "").strip()
        if not title:
            return jsonify({"status": "error"}), 400
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE chats SET title=%s WHERE id=%s AND user_id=%s", (title, chat_id, get_current_user_id()))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "renamed"})

    @app.route("/api/subjects", methods=["GET", "POST"])
    @login_required_api
    def subjects_api():
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "GET":
            data = fetch_subjects_with_topics(conn, uid)
            conn.close()
            return jsonify(data)

        body = request.get_json() or {}
        name = (body.get("name") or "").strip()
        semester = (body.get("semester") or "").strip()
        level = int(body.get("proficiencyLevel", 0) or 0)
        if not name or not semester:
            conn.close()
            return jsonify({"message": "name and semester are required"}), 400

        cur = conn.cursor()
        cur.execute("INSERT INTO subjects (user_id, name, semester, proficiency_level) VALUES (%s, %s, %s, %s)", (uid, name, semester, level))
        subject_id = cur.lastrowid
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, name, semester, proficiency_level, created_at FROM subjects WHERE id=%s AND user_id=%s", (subject_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(subject_to_api(row)), 201

    @app.route("/api/subjects/<int:subject_id>", methods=["PUT", "DELETE"])
    @login_required_api
    def subject_detail_api(subject_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "DELETE":
            cur = conn.cursor()
            cur.execute("DELETE FROM subjects WHERE id=%s AND user_id=%s", (subject_id, uid))
            conn.commit()
            cur.close()
            conn.close()
            return ("", 204)

        data = request.get_json() or {}
        updates, params = [], []
        if "name" in data:
            updates.append("name=%s")
            params.append((data.get("name") or "").strip())
        if "semester" in data:
            updates.append("semester=%s")
            params.append((data.get("semester") or "").strip())
        if "proficiencyLevel" in data:
            updates.append("proficiency_level=%s")
            params.append(int(data.get("proficiencyLevel") or 0))
        if not updates:
            conn.close()
            return jsonify({"message": "No valid fields to update"}), 400

        params.extend([subject_id, uid])
        cur = conn.cursor()
        cur.execute(f"UPDATE subjects SET {', '.join(updates)} WHERE id=%s AND user_id=%s", tuple(params))
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, name, semester, proficiency_level, created_at FROM subjects WHERE id=%s AND user_id=%s", (subject_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"message": "Subject not found"}), 404
        return jsonify(subject_to_api(row))

    @app.route("/api/subjects/<int:subject_id>/topics", methods=["POST"])
    @login_required_api
    def create_topic(subject_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"message": "name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        if not require_owned_row(cur, "subjects", subject_id, uid):
            cur.close()
            conn.close()
            return jsonify({"message": "Subject not found"}), 404

        unit_id = data.get("unitId")
        if unit_id is not None:
            cur.execute("SELECT id FROM units WHERE id=%s AND subject_id=%s", (unit_id, subject_id))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({"message": "Unit not found"}), 404

        is_completed = 1 if bool(data.get("isCompleted", False)) else 0
        confidence = int(data.get("confidence", 0) or 0)
        cur.execute(
            "INSERT INTO topics (subject_id, unit_id, name, is_completed, confidence) VALUES (%s, %s, %s, %s, %s)",
            (subject_id, unit_id, name, is_completed, confidence),
        )
        topic_id = cur.lastrowid
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, subject_id, unit_id, name, is_completed, confidence FROM topics WHERE id=%s", (topic_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(topic_to_api(row)), 201

    @app.route("/api/subjects/<int:subject_id>/units", methods=["POST"])
    @login_required_api
    def create_unit(subject_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        unit_no = (data.get("unitNo") or "").strip() or None
        description = (data.get("description") or "").strip() or None
        if not name:
            return jsonify({"message": "name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        if not require_owned_row(cur, "subjects", subject_id, uid):
            cur.close()
            conn.close()
            return jsonify({"message": "Subject not found"}), 404

        cur.execute(
            "INSERT INTO units (subject_id, unit_no, name, description) VALUES (%s, %s, %s, %s)",
            (subject_id, unit_no, name, description),
        )
        unit_id = cur.lastrowid
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, subject_id, unit_no, name, description, created_at FROM units WHERE id=%s",
            (unit_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({**unit_to_api(row), "topics": []}), 201

    @app.route("/api/subjects/import-syllabus", methods=["POST"])
    @login_required_api
    def import_syllabus():
        ensure_tables_initialized()
        uid = get_current_user_id()
        name = (request.form.get("name") or "").strip()
        semester = (request.form.get("semester") or "").strip()
        level = int(request.form.get("proficiencyLevel", 0) or 0)
        syllabus = request.files.get("syllabus")
        if not name or not semester:
            return jsonify({"message": "name and semester are required"}), 400
        if not syllabus or not syllabus.filename:
            return jsonify({"message": "syllabus PDF is required"}), 400
        if not syllabus.filename.lower().endswith(".pdf"):
            return jsonify({"message": "Only PDF files are supported"}), 400

        try:
            text = _extract_pdf_text(syllabus)
            parsed_units = _parse_units_and_topics(text, subject_name=name)
        except RuntimeError as exc:
            return jsonify({"message": str(exc)}), 500
        except Exception as exc:
            return jsonify({"message": f"Failed to parse syllabus: {str(exc)}"}), 500

        if not parsed_units:
            return jsonify(
                {
                    "message": f"Could not detect units/topics for subject '{name}'. "
                    "Use the exact subject name from the PDF heading."
                }
            ), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO subjects (user_id, name, semester, proficiency_level) VALUES (%s, %s, %s, %s)",
            (uid, name, semester, level),
        )
        subject_id = cur.lastrowid

        topics_created = 0
        units_created = 0
        for unit in parsed_units:
            cur.execute(
                "INSERT INTO units (subject_id, unit_no, name) VALUES (%s, %s, %s)",
                (subject_id, unit.get("unitNo"), unit["name"]),
            )
            unit_id = cur.lastrowid
            units_created += 1
            for topic in unit["topics"]:
                cur.execute(
                    "INSERT INTO topics (subject_id, unit_id, name, is_completed, confidence) VALUES (%s, %s, %s, 0, 0)",
                    (subject_id, unit_id, topic),
                )
                topics_created += 1

        conn.commit()
        cur.close()

        payload = fetch_subjects_with_topics(conn, uid)
        conn.close()
        created = next((s for s in payload if s["id"] == subject_id), None)
        return jsonify(
            {
                "subject": created,
                "summary": {
                    "unitsCreated": units_created,
                    "topicsCreated": topics_created,
                    "parsedUnits": len(parsed_units),
                },
            }
        ), 201

    @app.route("/api/topics/<int:topic_id>", methods=["PUT", "DELETE"])
    @login_required_api
    def topic_detail(topic_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        cur = conn.cursor()
        cur.execute("SELECT t.id FROM topics t JOIN subjects s ON s.id=t.subject_id WHERE t.id=%s AND s.user_id=%s", (topic_id, uid))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"message": "Topic not found"}), 404

        if request.method == "DELETE":
            cur.execute("DELETE FROM topics WHERE id=%s", (topic_id,))
            conn.commit()
            cur.close()
            conn.close()
            return ("", 204)

        data = request.get_json() or {}
        updates, params = [], []
        if "name" in data:
            updates.append("name=%s")
            params.append((data.get("name") or "").strip())
        if "isCompleted" in data:
            updates.append("is_completed=%s")
            params.append(1 if bool(data.get("isCompleted")) else 0)
        if "confidence" in data:
            updates.append("confidence=%s")
            params.append(int(data.get("confidence") or 0))
        if "unitId" in data:
            unit_id = data.get("unitId")
            if unit_id is None:
                updates.append("unit_id=%s")
                params.append(None)
            else:
                c2 = conn.cursor()
                c2.execute(
                    "SELECT u.id FROM units u JOIN topics t ON t.subject_id=u.subject_id WHERE t.id=%s AND u.id=%s",
                    (topic_id, unit_id),
                )
                is_valid = c2.fetchone() is not None
                c2.close()
                if not is_valid:
                    cur.close()
                    conn.close()
                    return jsonify({"message": "Unit not found"}), 404
                updates.append("unit_id=%s")
                params.append(unit_id)
        if not updates:
            conn.close()
            return jsonify({"message": "No valid fields to update"}), 400

        params.append(topic_id)
        cur.execute(f"UPDATE topics SET {', '.join(updates)} WHERE id=%s", tuple(params))
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, subject_id, unit_id, name, is_completed, confidence FROM topics WHERE id=%s", (topic_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(topic_to_api(row))

    @app.route("/api/skills", methods=["GET", "POST"])
    @login_required_api
    def skills_api():
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "GET":
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, user_id, name, category, proficiency_level FROM skills WHERE user_id=%s ORDER BY id DESC", (uid,))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return jsonify([skill_to_api(r) for r in rows])

        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        category = (data.get("category") or "").strip()
        level = int(data.get("proficiencyLevel", 0) or 0)
        if not name or not category:
            conn.close()
            return jsonify({"message": "name and category are required"}), 400

        cur = conn.cursor()
        cur.execute("INSERT INTO skills (user_id, name, category, proficiency_level) VALUES (%s, %s, %s, %s)", (uid, name, category, level))
        skill_id = cur.lastrowid
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, name, category, proficiency_level FROM skills WHERE id=%s AND user_id=%s", (skill_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(skill_to_api(row)), 201

    @app.route("/api/skills/<int:skill_id>", methods=["PUT", "DELETE"])
    @login_required_api
    def skill_detail(skill_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "DELETE":
            cur = conn.cursor()
            cur.execute("DELETE FROM skills WHERE id=%s AND user_id=%s", (skill_id, uid))
            conn.commit()
            cur.close()
            conn.close()
            return ("", 204)

        data = request.get_json() or {}
        updates, params = [], []
        if "name" in data:
            updates.append("name=%s")
            params.append((data.get("name") or "").strip())
        if "category" in data:
            updates.append("category=%s")
            params.append((data.get("category") or "").strip())
        if "proficiencyLevel" in data:
            updates.append("proficiency_level=%s")
            params.append(int(data.get("proficiencyLevel") or 0))
        if not updates:
            conn.close()
            return jsonify({"message": "No valid fields to update"}), 400

        params.extend([skill_id, uid])
        cur = conn.cursor()
        cur.execute(f"UPDATE skills SET {', '.join(updates)} WHERE id=%s AND user_id=%s", tuple(params))
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, name, category, proficiency_level FROM skills WHERE id=%s AND user_id=%s", (skill_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"message": "Skill not found"}), 404
        return jsonify(skill_to_api(row))

    @app.route("/api/applications", methods=["GET", "POST"])
    @login_required_api
    def applications_api():
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "GET":
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, user_id, company, role, status, applied_date FROM applications WHERE user_id=%s ORDER BY id DESC", (uid,))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return jsonify([application_to_api(r) for r in rows])

        data = request.get_json() or {}
        company = (data.get("company") or "").strip()
        role = (data.get("role") or "").strip()
        status = (data.get("status") or "").strip()
        applied_date = parse_datetime(data.get("appliedDate"))
        if not company or not role or not status:
            conn.close()
            return jsonify({"message": "company, role and status are required"}), 400

        cur = conn.cursor()
        cur.execute("INSERT INTO applications (user_id, company, role, status, applied_date) VALUES (%s, %s, %s, %s, %s)", (uid, company, role, status, applied_date))
        row_id = cur.lastrowid
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, company, role, status, applied_date FROM applications WHERE id=%s AND user_id=%s", (row_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(application_to_api(row)), 201

    @app.route("/api/applications/<int:application_id>", methods=["PUT", "DELETE"])
    @login_required_api
    def application_detail(application_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "DELETE":
            cur = conn.cursor()
            cur.execute("DELETE FROM applications WHERE id=%s AND user_id=%s", (application_id, uid))
            conn.commit()
            cur.close()
            conn.close()
            return ("", 204)

        data = request.get_json() or {}
        updates, params = [], []
        if "company" in data:
            updates.append("company=%s")
            params.append((data.get("company") or "").strip())
        if "role" in data:
            updates.append("role=%s")
            params.append((data.get("role") or "").strip())
        if "status" in data:
            updates.append("status=%s")
            params.append((data.get("status") or "").strip())
        if "appliedDate" in data:
            updates.append("applied_date=%s")
            params.append(parse_datetime(data.get("appliedDate")))
        if not updates:
            conn.close()
            return jsonify({"message": "No valid fields to update"}), 400

        params.extend([application_id, uid])
        cur = conn.cursor()
        cur.execute(f"UPDATE applications SET {', '.join(updates)} WHERE id=%s AND user_id=%s", tuple(params))
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, company, role, status, applied_date FROM applications WHERE id=%s AND user_id=%s", (application_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"message": "Application not found"}), 404
        return jsonify(application_to_api(row))

    @app.route("/api/study-plans", methods=["GET", "POST"])
    @login_required_api
    def study_plans_api():
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "GET":
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, user_id, title, description, target_date, is_completed FROM study_plans WHERE user_id=%s ORDER BY id DESC", (uid,))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return jsonify([study_plan_to_api(r) for r in rows])

        data = request.get_json() or {}
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip() or None
        target_date = parse_datetime(data.get("targetDate"))
        is_completed = 1 if bool(data.get("isCompleted", False)) else 0
        if not title:
            conn.close()
            return jsonify({"message": "title is required"}), 400

        cur = conn.cursor()
        cur.execute("INSERT INTO study_plans (user_id, title, description, target_date, is_completed) VALUES (%s, %s, %s, %s, %s)", (uid, title, description, target_date, is_completed))
        row_id = cur.lastrowid
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, title, description, target_date, is_completed FROM study_plans WHERE id=%s AND user_id=%s", (row_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(study_plan_to_api(row)), 201

    @app.route("/api/study-plans/<int:plan_id>", methods=["PUT", "DELETE"])
    @login_required_api
    def study_plan_detail(plan_id):
        ensure_tables_initialized()
        uid = get_current_user_id()
        conn = get_db_connection()

        if request.method == "DELETE":
            cur = conn.cursor()
            cur.execute("DELETE FROM study_plans WHERE id=%s AND user_id=%s", (plan_id, uid))
            conn.commit()
            cur.close()
            conn.close()
            return ("", 204)

        data = request.get_json() or {}
        updates, params = [], []
        if "title" in data:
            updates.append("title=%s")
            params.append((data.get("title") or "").strip())
        if "description" in data:
            d = (data.get("description") or "").strip()
            updates.append("description=%s")
            params.append(d or None)
        if "targetDate" in data:
            updates.append("target_date=%s")
            params.append(parse_datetime(data.get("targetDate")))
        if "isCompleted" in data:
            updates.append("is_completed=%s")
            params.append(1 if bool(data.get("isCompleted")) else 0)
        if not updates:
            conn.close()
            return jsonify({"message": "No valid fields to update"}), 400

        params.extend([plan_id, uid])
        cur = conn.cursor()
        cur.execute(f"UPDATE study_plans SET {', '.join(updates)} WHERE id=%s AND user_id=%s", tuple(params))
        conn.commit()
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, user_id, title, description, target_date, is_completed FROM study_plans WHERE id=%s AND user_id=%s", (plan_id, uid))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"message": "Study plan not found"}), 404
        return jsonify(study_plan_to_api(row))

    @app.route("/api/tutor/chat", methods=["POST"])
    @login_required_api
    def tutor_chat_api():
        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        context = (data.get("context") or "").strip()
        if not message:
            return jsonify({"message": "message is required"}), 400

        ctx = f"Context about the user: {context}\n\n" if context else ""
        try:
            result = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Content(role="user", parts=[types.Part(text=f"{ctx}{message}")])],
                config=types.GenerateContentConfig(
                    system_instruction="You are an AI Tutor helping a student with their Academic, Skill, Placement, and Planning goals.",
                    temperature=0.7,
                ),
            )
            return jsonify({"response": result.text or ""})
        except Exception as exc:
            return jsonify({"message": f"Failed to generate response: {str(exc)}"}), 500
