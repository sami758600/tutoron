from functools import wraps

from flask import jsonify, redirect, session, url_for


def get_current_user_id():
    return session.get("user_id")


def get_current_username():
    return session.get("username")


def login_required_page(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not get_current_user_id():
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)

    return wrapper


def login_required_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not get_current_user_id():
            return jsonify({"message": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper

