"""Memora — Flask application."""
import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import smtplib
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from email.message import EmailMessage
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import db
import generator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_VERSION = "12.4.0"


def _load_dotenv():
    """Load a simple KEY=VALUE .env file without requiring python-dotenv."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_dotenv()


def _load_secret():
    """Return a stable secret key: env var first, else a persisted file.

    Persisting the key means signed cookies (sessions, guest limit) survive
    restarts instead of logging everyone out on every boot.
    """
    env = os.environ.get("MEMORA_SECRET")
    if env:
        return env
    d = os.path.expanduser("~/.memora-data")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "secret.key")
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = f.read().strip()
        if s:
            return s
    except FileNotFoundError:
        pass
    s = secrets.token_urlsafe(48)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    return s

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max payload
app.secret_key = _load_secret()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NOTES_LEN = 100_000
MIN_PASSWORD_LEN = 8
RESET_CODE_TTL = 5 * 60  # password reset codes valid for 5 minutes

GUEST_COOKIE = "memora_guest"
_guest_signer = URLSafeTimedSerializer(app.secret_key, salt="memora-guest")

def _make_guest_id():
    return "g-" + secrets.token_urlsafe(16)

def _guest_from_cookie():
    raw = request.cookies.get(GUEST_COOKIE)
    if not raw:
        return None
    try:
        return _guest_signer.loads(raw, max_age=60 * 60 * 24 * 365)
    except (BadSignature, SignatureExpired):
        return None

def _set_guest_cookie(resp, guest_id):
    resp.set_cookie(
        GUEST_COOKIE, _guest_signer.dumps(guest_id),
        httponly=True, samesite="Lax", max_age=60 * 60 * 24 * 365,
    )

# Simple in-memory sliding-window rate limiter. Keys are "ip:identity".
_rate_hits = defaultdict(list)

def _rate_limit(key, limit, window):
    """Return True if the request is allowed, False if it exceeds the limit."""
    now = time.time()
    hits = _rate_hits[key]
    # prune expired entries
    while hits and hits[0] <= now - window:
        hits.pop(0)
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True


def _rate_key():
    ident = _guest_from_cookie()
    if not ident:
        user = _current_user()
        ident = f"user:{user['id']}" if user else (_anon_guest_id() or "anon")
    return f"{request.remote_addr or '0.0.0.0'}:{ident}"


def _throttle(limit, window, retry_after=None):
    """Decorator helper: reject requests over a sliding-window limit with 429."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not _rate_limit(_rate_key(), limit, window):
                resp = jsonify({"error": "Too many requests. Please slow down and try again."})
                resp.status_code = 429
                resp.headers["Retry-After"] = retry_after or str(int(window))
                return resp
            return fn(*a, **kw)
        return wrapper
    return deco


# ------------------------------------------------------------------ error handlers
@app.errorhandler(HTTPException)
def handle_http_exception(e):
    """Return clean JSON for standard HTTP errors."""
    return jsonify({"error": e.description}), e.code


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request"}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Resource not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(413)
def payload_too_large(e):
    return jsonify({"error": f"Payload too large. Maximum size is {MAX_NOTES_LEN} characters."}), 413


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Internal server error: %s", e)
    return jsonify({"error": "An internal server error occurred."}), 500


# ------------------------------------------------------------------ helpers
def _current_user():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    return db.get_user_by_token(token)


def _public_user(user):
    if not user:
        return None
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


def _anon_guest_id():
    return (request.headers.get("X-Guest-Id") or "").strip() or None


def _deck_for(user, card_id):
    if not user or not card_id:
        return None
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT c.deck_id FROM cards c JOIN decks d ON d.id=c.deck_id "
            "WHERE c.id=? AND d.user_id=?",
            (card_id, user["id"]),
        ).fetchone()
    return row["deck_id"] if row else None


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return app.send_static_file("index.html")


# ------------------------------------------------------------------ auth
@app.route("/api/auth/register", methods=["POST"])
@_throttle(10, 60)
def register():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    name = str(data.get("name") or "").strip()
    password = str(data.get("password") or "")

    if not email or not EMAIL_RE.match(email) or len(email) > 120:
        return jsonify({"error": "Please enter a valid email address."}), 400
    if len(password) < MIN_PASSWORD_LEN or len(password) > 128:
        return jsonify({"error": f"Password must be between {MIN_PASSWORD_LEN} and 128 characters."}), 400
    if not name:
        name = email.split("@")[0]
    name = name[:80]

    if db.get_user_by_email(email):
        return jsonify({"error": "An account with that email already exists."}), 409

    user_id = db.create_user(email, generate_password_hash(password), name)
    token = secrets.token_urlsafe(32)
    db.create_token(token, user_id)
    return jsonify({"token": token, "user": _public_user(db.get_user(user_id))}), 201


@app.route("/api/auth/login", methods=["POST"])
@_throttle(10, 60)
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = db.get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401

    token = secrets.token_urlsafe(32)
    db.create_token(token, user["id"])
    return jsonify({"token": token, "user": _public_user(user)})


@app.route("/api/auth/me")
def me():
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401
    return jsonify({"user": _public_user(user)})


@app.route("/api/config")
def config():
    """Expose client-side config flags (never secrets)."""
    return jsonify({
        "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        "version": APP_VERSION,
    })


GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
_GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo?id_token={id}"


@app.route("/api/auth/google", methods=["POST"])
@_throttle(10, 60)
def google_login():
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google sign-in is not configured."}), 503

    data = request.get_json(silent=True) or {}
    credential = str(data.get("credential") or "").strip()
    if not credential:
        return jsonify({"error": "Missing Google credential."}), 400

    # Verify the ID token with Google (no client secret needed for this flow).
    try:
        url = _GOOGLE_TOKENINFO.format(id=urllib.parse.quote(credential, safe=""))
        req = urllib.request.Request(url, headers={"User-Agent": "Memora/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception:
        return jsonify({"error": "Could not verify Google sign-in."}), 401

    if not isinstance(info, dict) or info.get("aud") != GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google credential did not verify."}), 401
    if not info.get("email_verified"):
        return jsonify({"error": "Please use a verified Google account."}), 401

    email = str(info.get("email") or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "Could not determine your Google email."}), 400

    name = str(info.get("name") or email.split("@")[0]).strip()[:80]
    user = db.get_user_by_email(email)
    if not user:
        user_id = db.create_user(email, generate_password_hash(secrets.token_urlsafe(32)), name)
        user = db.get_user(user_id)

    token = secrets.token_urlsafe(32)
    db.create_token(token, user["id"])
    return jsonify({"token": token, "user": _public_user(user)})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if token:
        db.delete_token(token)
    return jsonify({"ok": True})


@app.route("/api/auth/change-password", methods=["POST"])
@_throttle(10, 60)
def change_password():
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    data = request.get_json(silent=True) or {}
    current = str(data.get("current_password") or "")
    new = str(data.get("new_password") or "")

    if not check_password_hash(user["password_hash"], current):
        return jsonify({"error": "Current password is incorrect."}), 400
    if len(new) < MIN_PASSWORD_LEN or len(new) > 128:
        return jsonify({"error": f"New password must be between {MIN_PASSWORD_LEN} and 128 characters."}), 400

    db.update_password(user["id"], generate_password_hash(new))
    db.delete_all_tokens(user["id"])
    return jsonify({"ok": True})


# ------------------------------------------------------------------ password reset (email code)
def _send_password_code(email, code):
    host = os.environ.get("SMTP_HOST")
    if not host:
        # No SMTP configured: log the code so the flow is testable in dev.
        logger.warning("SMTP not configured. Password reset code for %s is: %s", email, code)
        return False
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASS")
        sender = os.environ.get("SMTP_FROM") or user
        msg = EmailMessage()
        msg["Subject"] = "Your Memora password reset code"
        msg["From"] = sender
        msg["To"] = email
        msg.set_content(
            f"Hi,\n\nWe received a request to reset your Memora password.\n\n"
            f"Your verification code is: {code}\n\n"
            f"Enter it on the site to set a new password. It expires in 5 minutes.\n"
            f"If you didn't request this, you can safely ignore this email.\n\n— Memora"
        )
        server = smtplib.SMTP(host, port, timeout=15)
        server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as exc:
        logger.warning("Failed to send password reset email: %s", exc)
        return False


@app.route("/api/auth/forgot-password", methods=["POST"])
@_throttle(5, 300)
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (str(data.get("email") or "").strip().lower())
    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "Please enter a valid email address."}), 400

    user = db.get_user_by_email(email)
    if user:
        code = f"{secrets.randbelow(1000000):06d}"
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        db.clear_resets_for_user(user["id"])
        db.create_password_reset(user["id"], code_hash, int(time.time()) + RESET_CODE_TTL)
        _send_password_code(email, code)
    # Always return ok to avoid account enumeration.
    return jsonify({"ok": True})


@app.route("/api/auth/reset-password", methods=["POST"])
@_throttle(5, 300)
def reset_password():
    data = request.get_json(silent=True) or {}
    email = (str(data.get("email") or "").strip().lower())
    code = str(data.get("code") or "").strip()
    new_password = str(data.get("new_password") or "")

    if not email or not code or not new_password:
        return jsonify({"error": "Email, code, and new password are required."}), 400
    if len(new_password) < MIN_PASSWORD_LEN or len(new_password) > 128:
        return jsonify({"error": f"New password must be between {MIN_PASSWORD_LEN} and 128 characters."}), 400

    user = db.get_user_by_email(email)
    if not user:
        return jsonify({"error": "Invalid or expired code."}), 400

    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    uid = db.find_valid_reset(code_hash)
    if uid is None or uid != user["id"]:
        return jsonify({"error": "Invalid or expired code."}), 400

    db.update_password(user["id"], generate_password_hash(new_password))
    db.delete_all_tokens(user["id"])
    db.clear_resets_for_user(user["id"])
    return jsonify({"ok": True})


@app.route("/api/due")
def due_cards():
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401
    return jsonify({"cards": db.get_due_cards(user["id"])})


@app.route("/api/changelog")
def changelog():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CHANGELOG.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = "# Changelog\n\nNo entries yet."
    return jsonify({"changelog": text})


# ------------------------------------------------------------------ decks
@app.route("/api/decks", methods=["GET"])
def decks_list():
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401
    return jsonify({"decks": db.list_decks(user["id"])})


@app.route("/api/decks", methods=["POST"])
def decks_create():
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    # Enforce a per-account deck cap. Not surfaced in the UI until the user
    # actually hits it.
    MAX_DECKS = 25
    if len(db.list_decks(user["id"])) >= MAX_DECKS:
        return jsonify({
            "error": "deck_limit",
            "message": f"You've reached the {MAX_DECKS}-deck limit. Delete a deck to make room for a new one."
        }), 403

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "Untitled deck").strip()[:120]
    subject = str(data.get("subject") or "Other").strip()[:80]
    if not name:
        name = "Untitled deck"

    deck_id = db.create_deck(user["id"], name, subject)

    # Seed with generated cards if provided
    cards = data.get("cards")
    if isinstance(cards, list) and cards:
        valid_cards = []
        for c in cards[:500]:
            if isinstance(c, dict):
                f = str(c.get("front", "")).strip()[:2000]
                b = str(c.get("back", "")).strip()[:5000]
                s = str(c.get("style", "q&a")).strip()[:20]
                if f and b:
                    valid_cards.append({"front": f, "back": b, "style": s})
        if valid_cards:
            db.add_cards(deck_id, valid_cards)

    deck = db.get_deck(user["id"], deck_id)
    return jsonify({"deck": deck}), 201


@app.route("/api/decks/<int:deck_id>", methods=["GET"])
def deck_get(deck_id):
    if deck_id <= 0:
        return jsonify({"error": "Invalid deck ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck = db.get_deck(user["id"], deck_id)
    if not deck:
        return jsonify({"error": "Deck not found"}), 404

    deck["cards"] = db.get_cards(deck_id)
    deck["last_feedback"] = build_feedback(deck, deck["cards"])
    return jsonify({"deck": deck})


def build_feedback(deck, cards):
    """Summarize the most recent study round for this deck."""
    s = db.last_deck_session(deck["id"])
    if not s:
        return None
    try:
        missed = json.loads(s["missed"] or "[]")
    except Exception:
        missed = []
    by_id = {c["id"]: c for c in cards}
    missed_cards = [by_id[m] for m in missed if m in by_id]
    acc = round(100 * s["correct_count"] / s["cards_reviewed"]) if s["cards_reviewed"] else 0
    return {
        "reviewed": s["cards_reviewed"],
        "correct": s["correct_count"],
        "accuracy": acc,
        "missed": [{"id": c["id"], "front": c["front"]} for c in missed_cards],
    }


@app.route("/api/decks/<int:deck_id>", methods=["PATCH"])
def deck_update(deck_id):
    if deck_id <= 0:
        return jsonify({"error": "Invalid deck ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck = db.get_deck(user["id"], deck_id)
    if not deck:
        return jsonify({"error": "Deck not found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = str(data["name"] or "Untitled deck").strip()[:120]
        db.rename_deck(user["id"], deck_id, name or "Untitled deck")
    if "favorite" in data:
        db.set_favorite(user["id"], deck_id, bool(data["favorite"]))

    return jsonify({"deck": db.get_deck(user["id"], deck_id)})


@app.route("/api/decks/<int:deck_id>", methods=["DELETE"])
def deck_delete(deck_id):
    if deck_id <= 0:
        return jsonify({"error": "Invalid deck ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck = db.get_deck(user["id"], deck_id)
    if not deck:
        return jsonify({"error": "Deck not found"}), 404

    if deck.get("favorite"):
        return jsonify({"error": "favourite_locked",
                        "message": "Unfavorite this deck before deleting it."}), 409

    db.delete_deck(user["id"], deck_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ cards
@app.route("/api/decks/<int:deck_id>/cards", methods=["POST"])
def cards_add(deck_id):
    if deck_id <= 0:
        return jsonify({"error": "Invalid deck ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck = db.get_deck(user["id"], deck_id)
    if not deck:
        return jsonify({"error": "Deck not found"}), 404

    data = request.get_json(silent=True) or {}
    front = str(data.get("front") or "").strip()[:2000]
    back = str(data.get("back") or "").strip()[:5000]
    style = str(data.get("style") or "q&a").strip()[:20]

    if not front or not back:
        return jsonify({"error": "Both front and back are required."}), 400

    card_id = db.add_one_card(deck_id, front, back, style)
    return jsonify({"card": db.get_card(deck_id, card_id)}), 201


@app.route("/api/cards/<int:card_id>", methods=["PATCH"])
def card_update(card_id):
    if card_id <= 0:
        return jsonify({"error": "Invalid card ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck_id = _deck_for(user, card_id)
    if not deck_id:
        return jsonify({"error": "Card not found"}), 404

    data = request.get_json(silent=True) or {}
    existing = db.get_card(deck_id, card_id)
    if not existing:
        return jsonify({"error": "Card not found"}), 404

    front = str(data.get("front", existing["front"])).strip()[:2000]
    back = str(data.get("back", existing["back"])).strip()[:5000]

    if not front or not back:
        return jsonify({"error": "Both front and back are required."}), 400

    db.update_card(deck_id, card_id, front, back)
    return jsonify({"card": db.get_card(deck_id, card_id)})


@app.route("/api/cards/<int:card_id>", methods=["DELETE"])
def card_delete(card_id):
    if card_id <= 0:
        return jsonify({"error": "Invalid card ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck_id = _deck_for(user, card_id)
    if not deck_id:
        return jsonify({"error": "Card not found"}), 404

    db.delete_card(deck_id, card_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ file upload
@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Extract text from an uploaded .txt or .pdf file and return it as notes."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file provided."}), 400

    fname = file.filename
    try:
        raw = file.read()
    except Exception:
        return jsonify({"error": "Could not read the file."}), 400
    if not raw:
        return jsonify({"error": "That file appears to be empty."}), 422

    text = ""
    if fname.lower().endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(pages)
        except Exception:
            return jsonify({"error": "Could not read the PDF (it may be scanned or encrypted)."}), 422
    elif fname.lower().endswith(".txt"):
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    else:
        return jsonify({"error": "Please upload a .txt or .pdf file."}), 400

    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return jsonify({"error": "No readable text was found in that file."}), 422
    return jsonify({"text": text[:MAX_NOTES_LEN]}), 200


@app.route("/api/generate", methods=["POST"])
@_throttle(30, 60)
def generate():
    data = request.get_json(silent=True) or {}
    notes = data.get("notes")

    if notes is None or not str(notes).strip():
        return jsonify({"error": "Please paste or enter your notes first."}), 400

    notes_str = str(notes).strip()
    if len(notes_str) > MAX_NOTES_LEN:
        return jsonify({"error": f"Notes payload is too large (maximum {MAX_NOTES_LEN:,} characters)."}), 400

    try:
        number = max(1, min(int(data.get("number") or 5), 50))
    except (ValueError, TypeError):
        number = 5

    subject = str(data.get("subject") or "Other").strip()[:80] or "Other"
    difficulty = str(data.get("difficulty") or "Medium").strip()
    if difficulty not in ("Easy", "Medium", "Hard"):
        difficulty = "Medium"

    style = str(data.get("style") or "q&a").strip()
    if style not in ("q&a", "term", "cloze", "mixed"):
        style = "q&a"

    user = _current_user()
    guest_id = None
    if not user:
        # Guests get exactly ONE flashcard, tracked by a server-side signed,
        # HttpOnly cookie (not a spoofable client-supplied header).
        guest_id = _guest_from_cookie()
        if guest_id is None:
            guest_id = _make_guest_id()
            db.set_guest_used(guest_id)
            number = 1
        elif db.guest_used_card(guest_id):
            return jsonify(
                {"error": "sign_in_required",
                 "message": "Your first flashcard is ready! Sign in to keep going."}
            ), 402
        else:
            db.set_guest_used(guest_id)
            number = 1

    cards = generator.generate(notes_str, subject, difficulty, number, style)
    for c in cards:
        c.setdefault("style", style)

    resp = jsonify(
        {"cards": cards,
         "limited": bool(not user and cards),
         "signed_in": bool(user)}
    )
    if guest_id:
        _set_guest_cookie(resp, guest_id)
    return resp


# ------------------------------------------------------------------ study
@app.route("/api/decks/<int:deck_id>/study", methods=["POST"])
def study(deck_id):
    if deck_id <= 0:
        return jsonify({"error": "Invalid deck ID"}), 400

    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    deck = db.get_deck(user["id"], deck_id)
    if not deck:
        return jsonify({"error": "Deck not found"}), 404

    data = request.get_json(silent=True) or {}
    results = data.get("results")
    if not isinstance(results, list):
        results = []

    try:
        seconds = max(0, int(data.get("seconds") or 0))
    except (ValueError, TypeError):
        seconds = 0

    correct = 0
    missed_ids = []
    for r in results:
        if isinstance(r, dict):
            card_id = r.get("card_id")
            knew = bool(r.get("knew"))
            if card_id:
                if knew:
                    correct += 1
                else:
                    missed_ids.append(card_id)
                db.update_card_stats(card_id, knew)

    db.add_study_session(user["id"], deck_id, len(results), correct, seconds, json.dumps(missed_ids))
    db.touch_studied(user["id"], deck_id)
    return jsonify({"ok": True, "correct": correct, "reviewed": len(results)})


@app.route("/api/smart/review", methods=["POST"])
def smart_review():
    """Record a cross-deck smart-review session."""
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    data = request.get_json(silent=True) or {}
    results = data.get("results")
    if not isinstance(results, list):
        results = []

    try:
        seconds = max(0, int(data.get("seconds") or 0))
    except (ValueError, TypeError):
        seconds = 0

    correct = 0
    missed_ids = []
    for r in results:
        if isinstance(r, dict):
            card_id = r.get("card_id")
            knew = bool(r.get("knew"))
            if card_id:
                if knew:
                    correct += 1
                else:
                    missed_ids.append(card_id)
                db.update_card_stats(card_id, knew)

    db.add_study_session(user["id"], None, len(results), correct, seconds, json.dumps(missed_ids))
    return jsonify({"ok": True, "correct": correct, "reviewed": len(results)})


# ------------------------------------------------------------------ stats
@app.route("/api/stats")
def stats():
    user = _current_user()
    if not user:
        return jsonify({"error": "Not signed in"}), 401

    data = db.user_stats(user["id"])
    by_day = {}
    for s in data["sessions"]:
        day = int(s["date"] // 86400)
        by_day[day] = by_day.get(day, 0) + s["seconds"]

    streak = 0
    day = int(datetime.datetime.now().timestamp() // 86400)
    if by_day.get(day):
        streak = 1
        d = day - 1
        while by_day.get(d):
            streak += 1
            d -= 1

    reviewed = sum(s["cards_reviewed"] for s in data["sessions"])
    total_seconds = sum(s["seconds"] for s in data["sessions"])

    return jsonify(
        {"total_cards": data["total_cards"],
         "mastered": data["mastered"],
         "cards_reviewed": reviewed,
         "total_study_seconds": total_seconds,
         "study_streak": streak,
         "daily": [{"day": int(d["date"] // 86400), "seconds": d["seconds"]} for d in data["sessions"]]}
    )


# ------------------------------------------------------------------ health
@app.route("/api/health")
def health():
    return jsonify({"ok": True, "name": "Memora", "version": APP_VERSION})


@app.route("/api/version")
def version():
    return jsonify({"name": "Memora", "version": APP_VERSION})


db.init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)