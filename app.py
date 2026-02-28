import os

from dotenv import load_dotenv
from flask import Flask
from google import genai

from app_routes import register_app_routes
from auth_routes import register_auth_routes
from db_utils import ensure_tables_initialized
from push_routes import register_push_routes
from reminder_routes import register_reminder_routes
from reminder_scheduler import start_reminder_scheduler

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-change-this-secret")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """
You are a professional AI Tutor.
1. Give a clear and precise definition first.
2. Explain the core idea in simple sentences.
3. Maintain logical order and structured flow.
4. Avoid unnecessary storytelling or motivational lines.
5. Use clean formatting with proper bullet points.
6. Include a small example when helpful.
7. End with a short key takeaway summary.
"""

# Register modular route sets.
register_auth_routes(app)
register_app_routes(app, client, SYSTEM_PROMPT)
register_reminder_routes(app, client)
register_push_routes(app)
start_reminder_scheduler()


@app.before_request
def _bootstrap_once():
    ensure_tables_initialized()


if __name__ == "__main__":
    app.run(debug=True)
