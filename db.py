"""Memora database layer.

Supports SQLite (default, used locally) and PostgreSQL (used automatically
when DATABASE_URL is set, e.g. a free Render managed Postgres) so user data
survives redeploys without needing a paid persistent disk.
"""
import os
import time
from contextlib import contextmanager

_LOCAL = os.path.join(os.path.expanduser("~"), "memora-data")
try:
    os.makedirs(_LOCAL, exist_ok=True)
except OSError:
    pass
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.environ.get("MEMORA_DB", os.path.join(_LOCAL, "memora.db"))

IS_PG = bool(DATABASE_URL)

# Ensure the folder that holds the local SQLite file exists.
if not IS_PG:
    try:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    except OSError:
        pass


def _ts():
    return int(time.time())


# ------------------------------------------------------------- engine helpers
if IS_PG:
    import psycopg2

    def _translate(sql):
        # PostgreSQL uses %s placeholders and SERIAL (not AUTOINCREMENT).
        return sql.replace("?", "%s").replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
        )

    def _targets_id(sql):
        # Tables that have an auto-generated `id` column (cards/users/decks/etc).
        u = sql.upper()
        return any(
            t in u
            for t in ("INTO USERS", "INTO DECKS", "INTO CARDS", "INTO STUDY_SESSIONS", "INTO PASSWORD_RESETS")
        )

    def _split_sql(script):
        return [s for s in script.split(";") if s.strip()]

    class _Row:
        __slots__ = ("_m", "_v")

        def __init__(self, cols, values):
            self._m = dict(zip(cols, values))
            self._v = values

        def __getitem__(self, key):
            if isinstance(key, int):
                return self._v[key]
            return self._m[key]

        def keys(self):
            return list(self._m.keys())

    class _Cursor:
        def __init__(self, cur, returning=False):
            self._cur = cur
            self.lastrowid = None
            if returning and cur.description:
                r = cur.fetchone()
                if r:
                    self.lastrowid = r[0]

        def fetchone(self):
            r = self._cur.fetchone()
            if r is None:
                return None
            cols = [d[0] for d in self._cur.description]
            return _Row(cols, r)

        def fetchall(self):
            if self._cur.description is None:
                return []
            cols = [d[0] for d in self._cur.description]
            return [_Row(cols, r) for r in self._cur.fetchall()]

    class _PgConn:
        def __init__(self, conn):
            self._c = conn

        def execute(self, sql, params=None):
            sql = _translate(sql)
            returning = sql.lstrip().upper().startswith("INSERT") and _targets_id(sql)
            if returning and " RETURNING " not in sql.upper():
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
            cur = self._c.cursor()
            cur.execute(sql, params if params is not None else ())
            return _Cursor(cur, returning)

        def executescript(self, script):
            for stmt in _split_sql(script):
                if not stmt.strip():
                    continue
                cur = self._c.cursor()
                cur.execute(_translate(stmt))

        def commit(self):
            self._c.commit()

        def rollback(self):
            self._c.rollback()

        def close(self):
            self._c.close()

    @contextmanager
    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        try:
            yield _PgConn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

else:
    import sqlite3

    @contextmanager
    def get_db():
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


SCHEMA = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guest_usage (
                guest_id TEXT PRIMARY KEY,
                card_used INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT 'Other',
                favorite INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                times_studied INTEGER NOT NULL DEFAULT 0,
                last_studied INTEGER
            );

            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                style TEXT NOT NULL DEFAULT 'q&a',
                position INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS card_stats (
                card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
                times_seen INTEGER NOT NULL DEFAULT 0,
                times_correct INTEGER NOT NULL DEFAULT 0,
                mastered INTEGER NOT NULL DEFAULT 0,
                reps INTEGER NOT NULL DEFAULT 0,
                interval INTEGER NOT NULL DEFAULT 0,
                ease REAL NOT NULL DEFAULT 2.5,
                due INTEGER
            );

            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                deck_id INTEGER,
                date INTEGER NOT NULL,
                cards_reviewed INTEGER NOT NULL,
                correct_count INTEGER NOT NULL,
                seconds INTEGER NOT NULL,
                missed TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rate_events (
                key TEXT NOT NULL,
                ts INTEGER NOT NULL
            );

            -- Indexes for fast query performance and referential integrity
            CREATE INDEX IF NOT EXISTS idx_tokens_token ON tokens(token);
            CREATE INDEX IF NOT EXISTS idx_tokens_user_id ON tokens(user_id);
            CREATE INDEX IF NOT EXISTS idx_decks_user_id ON decks(user_id);
            CREATE INDEX IF NOT EXISTS idx_cards_deck_id ON cards(deck_id);
            CREATE INDEX IF NOT EXISTS idx_cards_deck_pos ON cards(deck_id, position);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_id ON study_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_deck_id ON study_sessions(deck_id);
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user_date ON study_sessions(user_id, date);
            CREATE INDEX IF NOT EXISTS idx_rate_events_key_ts ON rate_events(key, ts);
            """


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)

    if IS_PG:
        with get_db() as db:
            db.execute(
                "ALTER TABLE study_sessions ADD COLUMN IF NOT EXISTS missed TEXT NOT NULL DEFAULT ''"
            )
            for ddl in (
                "ALTER TABLE card_stats ADD COLUMN IF NOT EXISTS reps INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE card_stats ADD COLUMN IF NOT EXISTS interval INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE card_stats ADD COLUMN IF NOT EXISTS ease REAL NOT NULL DEFAULT 2.5",
                "ALTER TABLE card_stats ADD COLUMN IF NOT EXISTS due INTEGER",
            ):
                db.execute(ddl)
            db.execute(
                """CREATE TABLE IF NOT EXISTS password_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    code_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )"""
            )
        return

    # --- SQLite-only migrations ---
    with get_db() as _con:
        cols = [c[1] for c in _con.execute("PRAGMA table_info(study_sessions)").fetchall()]
        if "missed" not in cols:
            _con.execute("ALTER TABLE study_sessions ADD COLUMN missed TEXT NOT NULL DEFAULT ''")

    with get_db() as _con:
        cols = [c[1] for c in _con.execute("PRAGMA table_info(card_stats)").fetchall()]
        for name, ddl in (("reps", "ALTER TABLE card_stats ADD COLUMN reps INTEGER NOT NULL DEFAULT 0"),
                          ("interval", "ALTER TABLE card_stats ADD COLUMN interval INTEGER NOT NULL DEFAULT 0"),
                          ("ease", "ALTER TABLE card_stats ADD COLUMN ease REAL NOT NULL DEFAULT 2.5"),
                          ("due", "ALTER TABLE card_stats ADD COLUMN due INTEGER")):
            if name not in cols:
                _con.execute(ddl)

    with get_db() as _con:
        _con.execute(
            """CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )"""
        )


# ---------------- users / auth ----------------
def create_user(email, password_hash, name):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO users (email, password_hash, name, created_at) VALUES (?,?,?,?)",
            (email, password_hash, name, _ts()),
        )
        return cur.lastrowid


def get_user_by_email(email):
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user(user_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_token(token, user_id):
    with get_db() as db:
        db.execute(
            "INSERT INTO tokens (token, user_id, created_at) VALUES (?,?,?)",
            (token, user_id, _ts()),
        )


def get_user_by_token(token):
    if not token:
        return None
    with get_db() as db:
        row = db.execute(
            "SELECT u.* FROM users u JOIN tokens t ON t.user_id = u.id WHERE t.token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row else None


def delete_token(token):
    """Revoke a single session token (used on logout)."""
    if not token:
        return
    with get_db() as db:
        db.execute("DELETE FROM tokens WHERE token = ?", (token,))


def delete_all_tokens(user_id):
    """Revoke every session for a user (used on password change / security)."""
    if not user_id:
        return
    with get_db() as db:
        db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))


def update_password(user_id, password_hash):
    if not user_id:
        return
    with get_db() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


def create_password_reset(user_id, code_hash, expires_at):
    with get_db() as db:
        db.execute(
            "INSERT INTO password_resets (user_id, code_hash, created_at, expires_at) VALUES (?,?,?,?)",
            (user_id, code_hash, _ts(), expires_at),
        )


def find_valid_reset(code_hash):
    """Return the user_id for a matching, unexpired reset code, or None."""
    now = _ts()
    with get_db() as db:
        row = db.execute(
            "SELECT user_id FROM password_resets WHERE code_hash = ? AND expires_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (code_hash, now),
        ).fetchone()
        return row["user_id"] if row else None


def clear_resets_for_user(user_id):
    with get_db() as db:
        db.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))


# ------------------------------------------------------------------ guest usage
def guest_used_card(guest_id):
    if not guest_id:
        return False
    with get_db() as db:
        row = db.execute(
            "SELECT card_used FROM guest_usage WHERE guest_id = ?", (guest_id,)
        ).fetchone()
        if row:
            return row["card_used"] == 1
        return False


def set_guest_used(guest_id):
    if not guest_id:
        return
    with get_db() as db:
        db.execute(
            "INSERT INTO guest_usage (guest_id, card_used) VALUES (?,1) "
            "ON CONFLICT(guest_id) DO UPDATE SET card_used = 1",
            (guest_id,),
        )


# ------------------------------------------------------------------ rate limiting
# Database-backed sliding-window limiter. Storing events in the DB (rather
# than in memory) means the limit is shared across all gunicorn workers and
# survives restarts, so it can't be bypassed by running multiple workers or
# redeploying. Works on both SQLite and PostgreSQL via the engine shim.

def rate_allowed(key, limit, window):
    """Prune expired hits for `key` and return True if a new hit fits the limit.

    `limit` = max hits allowed, `window` = seconds. Does NOT record the hit;
    call rate_record() after a True return.
    """
    if not key:
        return True
    now = _ts()
    cutoff = now - window
    with get_db() as db:
        db.execute("DELETE FROM rate_events WHERE key = ? AND ts < ?", (key, cutoff))
        row = db.execute(
            "SELECT COUNT(*) FROM rate_events WHERE key = ? AND ts >= ?",
            (key, cutoff),
        ).fetchone()
        count = row[0] if row else 0
        return count < limit


def rate_record(key):
    """Record a single hit for `key` (timestamped now)."""
    if not key:
        return
    with get_db() as db:
        db.execute("INSERT INTO rate_events (key, ts) VALUES (?,?)", (key, _ts()))


# ------------------------------------------------------------------ decks
def create_deck(user_id, name, subject):
    now = _ts()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO decks (user_id, name, subject, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, name, subject, now, now),
        )
        return cur.lastrowid


def list_decks(user_id):
    with get_db() as db:
        rows = db.execute(
            """SELECT d.*,
                      (SELECT COUNT(*) FROM cards c WHERE c.deck_id = d.id) AS card_count,
                      (SELECT COUNT(*) FROM cards c JOIN card_stats s ON s.card_id=c.id
                       WHERE c.deck_id = d.id AND s.mastered = 1) AS mastered_count,
                      (SELECT ROUND(100.0 * SUM(s.times_correct) / NULLIF(SUM(s.times_seen),0))
                       FROM cards c JOIN card_stats s ON s.card_id=c.id
                       WHERE c.deck_id = d.id) AS accuracy
               FROM decks d WHERE d.user_id = ? ORDER BY d.updated_at DESC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_deck(user_id, deck_id):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM decks WHERE id = ? AND user_id = ?", (deck_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def rename_deck(user_id, deck_id, name):
    with get_db() as db:
        db.execute(
            "UPDATE decks SET name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (name, _ts(), deck_id, user_id),
        )


def set_favorite(user_id, deck_id, fav):
    with get_db() as db:
        db.execute(
            "UPDATE decks SET favorite = ? WHERE id = ? AND user_id = ?",
            (1 if fav else 0, deck_id, user_id),
        )


def delete_deck(user_id, deck_id):
    with get_db() as db:
        db.execute("DELETE FROM decks WHERE id = ? AND user_id = ?", (deck_id, user_id))


def touch_studied(user_id, deck_id):
    with get_db() as db:
        db.execute(
            "UPDATE decks SET times_studied = times_studied + 1, last_studied = ? "
            "WHERE id = ? AND user_id = ?",
            (_ts(), deck_id, user_id),
        )


# ------------------------------------------------------------------ cards
def add_cards(deck_id, cards):
    if not cards:
        return
    with get_db() as db:
        pos_row = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM cards WHERE deck_id = ?",
            (deck_id,),
        ).fetchone()
        pos = pos_row[0] if pos_row else 0
        for card in cards:
            front = str(card.get("front", "")).strip()
            back = str(card.get("back", "")).strip()
            if not front or not back:
                continue
            db.execute(
                "INSERT INTO cards (deck_id, front, back, style, position, created_at) VALUES (?,?,?,?,?,?)",
                (deck_id, front, back, card.get("style", "q&a"), pos, _ts()),
            )
            pos += 1
        db.execute("UPDATE decks SET updated_at = ? WHERE id = ?", (_ts(), deck_id))


def add_one_card(deck_id, front, back, style):
    with get_db() as db:
        pos_row = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM cards WHERE deck_id = ?",
            (deck_id,),
        ).fetchone()
        pos = pos_row[0] if pos_row else 0
        cur = db.execute(
            "INSERT INTO cards (deck_id, front, back, style, position, created_at) VALUES (?,?,?,?,?,?)",
            (deck_id, front, back, style, pos, _ts()),
        )
        db.execute("UPDATE decks SET updated_at = ? WHERE id = ?", (_ts(), deck_id))
        return cur.lastrowid


def get_cards(deck_id):
    with get_db() as db:
        rows = db.execute(
            """SELECT c.*, s.times_seen, s.times_correct, s.mastered,
                       s.reps, s.interval AS srs_interval, s.ease, s.due
               FROM cards c LEFT JOIN card_stats s ON s.card_id = c.id
               WHERE c.deck_id = ? ORDER BY c.position""",
            (deck_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_card(deck_id, card_id):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
        ).fetchone()
        return dict(row) if row else None


def update_card(deck_id, card_id, front, back):
    with get_db() as db:
        db.execute(
            "UPDATE cards SET front = ?, back = ? WHERE id = ? AND deck_id = ?",
            (front, back, card_id, deck_id),
        )
        db.execute("UPDATE decks SET updated_at = ? WHERE id = ?", (_ts(), deck_id))


def delete_card(deck_id, card_id):
    with get_db() as db:
        db.execute(
            "DELETE FROM cards WHERE id = ? AND deck_id = ?", (card_id, deck_id)
        )
        db.execute("UPDATE decks SET updated_at = ? WHERE id = ?", (_ts(), deck_id))


def update_card_stats(card_id, correct):
    """Record a review and apply a lightweight SM-2 spaced-repetition schedule.

    Maps the binary rating to an SM-2 grade (knew -> 4, didn't know -> 2) and
    updates the per-card interval (days), ease factor, and due timestamp. A card
    is considered "mastered" once its interval reaches 3 days (i.e. it has been
    successfully reviewed out to a multi-day schedule).
    """
    now = _ts()
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM card_stats WHERE card_id = ?", (card_id,)
        ).fetchone()
        if row:
            reps = row["reps"]
            ease = row["ease"]
            interval = row["interval"]
            seen = row["times_seen"]
            corr = row["times_correct"]
            mastered = row["mastered"]
        else:
            reps, ease, interval, seen, corr, mastered = 0, 2.5, 0, 0, 0, 0

        seen += 1
        if correct:
            corr += 1
            reps += 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 6
            else:
                interval = max(1, round(interval * ease))
            # grade 4 for a correct review (ease nudged up slightly)
            ease = max(1.3, ease + (0.1 - (5 - 4) * (0.08 + (5 - 4) * 0.02)))
        else:
            reps = 0
            interval = 1
            ease = max(1.3, ease - 0.2)

        due = now + interval * 86400
        mastered = 1 if interval >= 3 else 0

        db.execute(
            """INSERT INTO card_stats
               (card_id, times_seen, times_correct, mastered, reps, interval, ease, due)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(card_id) DO UPDATE SET
                 times_seen = ?, times_correct = ?, mastered = ?,
                 reps = ?, interval = ?, ease = ?, due = ?""",
            (card_id, seen, corr, mastered, reps, interval, ease, due,
             seen, corr, mastered, reps, interval, ease, due),
        )


def get_due_cards(user_id):
    """Return cards (across all of a user's decks) that are due for review."""
    now = _ts()
    with get_db() as db:
        rows = db.execute(
            """SELECT c.id, c.deck_id, c.front, c.back, c.style,
                       s.reps, s.interval AS srs_interval, s.ease, s.due, s.times_correct, s.mastered
               FROM cards c
               JOIN decks d ON d.id = c.deck_id
               LEFT JOIN card_stats s ON s.card_id = c.id
               WHERE d.user_id = ? AND (s.due IS NULL OR s.due <= ?)
               ORDER BY s.due IS NULL DESC, s.due ASC""",
            (user_id, now),
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------ study / stats
def add_study_session(user_id, deck_id, cards_reviewed, correct_count, seconds, missed=""):
    with get_db() as db:
        db.execute(
            "INSERT INTO study_sessions (user_id, deck_id, date, cards_reviewed, correct_count, seconds, missed) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, deck_id, _ts(), cards_reviewed, correct_count, seconds, missed),
        )


def last_deck_session(deck_id):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM study_sessions WHERE deck_id = ? ORDER BY id DESC LIMIT 1",
            (deck_id,),
        ).fetchone()
        return dict(row) if row else None


def user_stats(user_id):
    with get_db() as db:
        total_cards_row = db.execute(
            "SELECT COUNT(*) FROM cards c JOIN decks d ON d.id = c.deck_id WHERE d.user_id = ?",
            (user_id,),
        ).fetchone()
        total_cards = total_cards_row[0] if total_cards_row else 0

        mastered_row = db.execute(
            """SELECT COUNT(*) FROM cards c JOIN decks d ON d.id=c.deck_id
               JOIN card_stats s ON s.card_id=c.id WHERE d.user_id = ? AND s.mastered=1""",
            (user_id,),
        ).fetchone()
        mastered = mastered_row[0] if mastered_row else 0

        sessions = db.execute(
            "SELECT * FROM study_sessions WHERE user_id = ? ORDER BY date", (user_id,)
        ).fetchall()
        return {"total_cards": total_cards, "mastered": mastered, "sessions": [dict(s) for s in sessions]}