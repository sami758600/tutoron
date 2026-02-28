import mysql.connector
from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import get_current_user_id, get_current_username, login_required_api
from db_utils import ensure_tables_initialized, get_db_connection


def register_auth_routes(app):
    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        ensure_tables_initialized()
        if request.method == "GET":
            if get_current_user_id():
                return redirect(url_for("dashboard_page"))
            return render_template("login.html", error=None)

        data = request.get_json(silent=True) or request.form
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""

        if not username or not password:
            if request.is_json:
                return jsonify({"message": "username and password are required"}), 400
            return render_template("login.html", error="Username and password are required.")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, username, password_hash FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            if request.is_json:
                return jsonify({"message": "Invalid credentials"}), 401
            return render_template("login.html", error="Invalid username or password.")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        if request.is_json:
            return jsonify({"status": "ok"})
        return redirect(url_for("dashboard_page"))

    @app.route("/register", methods=["GET", "POST"])
    def register_page():
        ensure_tables_initialized()
        if request.method == "GET":
            if get_current_user_id():
                return redirect(url_for("dashboard_page"))
            return render_template("register.html", error=None)

        data = request.get_json(silent=True) or request.form
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""

        if len(username) < 3 or len(password) < 6:
            msg = "Username must be 3+ chars and password must be 6+ chars."
            if request.is_json:
                return jsonify({"message": msg}), 400
            return render_template("register.html", error=msg)

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (username, generate_password_hash(password)),
            )
            conn.commit()
            user_id = cur.lastrowid
        except mysql.connector.IntegrityError:
            cur.close()
            conn.close()
            msg = "Username already exists."
            if request.is_json:
                return jsonify({"message": msg}), 409
            return render_template("register.html", error=msg)

        cur.close()
        conn.close()
        session["user_id"] = user_id
        session["username"] = username
        if request.is_json:
            return jsonify({"status": "ok"}), 201
        return redirect(url_for("dashboard_page"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    @app.route("/api/me")
    @login_required_api
    def api_me():
        return jsonify({"user_id": get_current_user_id(), "username": get_current_username()})

