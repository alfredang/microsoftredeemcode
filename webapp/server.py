"""Flask app: serves the static UI and exposes the Playwright-driven API."""

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from backend.generate import generate_codes
from backend.login import run_login
from backend.paths import COURSES_JSON, ROOT, STORAGE_STATE

app = Flask(__name__, static_folder=None)


@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:filename>")
def static_files(filename: str):
    # Only serve files that actually exist at the project root.
    target = (ROOT / filename).resolve()
    if not str(target).startswith(str(ROOT.resolve())):
        return ("forbidden", 403)
    if not target.is_file():
        return ("not found", 404)
    return send_from_directory(ROOT, filename)


@app.get("/api/status")
def status():
    return jsonify({"signedIn": STORAGE_STATE.exists()})


@app.post("/api/login")
def login():
    result = run_login()
    return jsonify(result), (200 if result.get("ok") else 400)


@app.post("/api/generate")
def generate():
    body = request.get_json(force=True, silent=True) or {}
    course_number = (body.get("courseNumber") or "").strip()
    count = int(body.get("count") or 0)
    students = int(body.get("students") or 1)

    if not course_number:
        return jsonify({"ok": False, "error": "courseNumber is required"}), 400
    if count < 1:
        return jsonify({"ok": False, "error": "count must be >= 1"}), 400

    courses = json.loads(Path(COURSES_JSON).read_text(encoding="utf-8"))
    match = next((c for c in courses if c["courseNumber"] == course_number), None)
    if not match:
        return jsonify({"ok": False, "error": f"Unknown course {course_number}"}), 404

    result = generate_codes(course_number, match["baseUrl"], count, students)
    http = 200 if result.get("ok") else 400
    return jsonify(result), http


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
