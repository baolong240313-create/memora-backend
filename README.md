# Memora 🧠

**Turn your notes into flashcards in seconds.** Memora is a student-focused web app that converts pasted notes (or uploaded text files) into interactive flashcards you can study with, track progress on, and save as decks.

## Features

- **Landing page** — hero, feature cards, and a tappable sample flashcard.
- **Flashcard generator** — paste notes or upload a `.txt`, choose subject, difficulty, card count, and card style, then generate.
- **One-free-flashcard rule** — signed-out users can generate **exactly 1 flashcard**; after that they're prompted to sign in. The limit persists across page refreshes (tracked server-side by guest id) and can't be bypassed by reopening the page. Signed-in users get full generation.
- **Decks** — create, rename, favorite, delete, search, and sort (newest / oldest / most studied).
- **Card editor** — edit, add, delete, and regenerate individual cards.
- **Study mode** — one card at a time with a smooth 3D flip, self-rated verdicts (Didn't Know / Almost / Knew It), a summary (accuracy, study time, cards needing practice), and an optional **shuffle toggle** so you don't just memorize the order.
- **Quiz mode** — test yourself with multiple-choice questions (answers pulled from your own deck), with instant feedback and a final score.
- **Quizzes section** — a dedicated **Quizzes** page to **create an AI quiz** on English, Math, or Science (score revealed only at the end), or turn any of your decks into a quiz.
- **Import decks** — paste terms from Anki/Quizlet exports (or `Term: Definition` / `Term — Definition` lines) and turn them into a deck instantly.
- **Deck-by-deck review** — the "To review" dashboard card lists your weak cards grouped by deck, so you choose which deck to refresh first.
- **AI flashcards from a topic** — in "Paste in Your Studies", type a topic and the AI researches and writes the flashcards for you (like the AI quiz).
- **Download decks** — export any deck as a **PDF**, **TXT**, or **JSON** file to keep or share your flashcards.
- **Progress** — per-deck progress bars, plus a statistics page with daily study time, cards reviewed, accuracy, and study streak.
- **Polish** — light/dark mode, responsive layout, page transitions, toasts, confirm dialogs, and empty states.

## Tech

- **Backend:** Python + Flask + SQLite (persistent accounts, decks, cards, and study history).
- **Frontend:** a single-page app (vanilla JS, no build step) served by Flask.
- **Auth:** token-based sessions stored in `localStorage`. Passwords hashed with Werkzeug.
- **Generation:** a real-AI-ready `generate()` interface in `generator.py` that currently produces notes-grounded demo/fallback flashcards (it never fabricates facts). Swap in an LLM API by implementing the same signature.

## Run it

```bash
cd memora
pip install -r requirements.txt
python app.py
# then open http://localhost:5000
```

## Configuration (optional)

| Env var | Purpose |
|---|---|
| `MEMORA_SECRET` | Secret used to sign session/guest cookies. Set a long random value in production. Defaults to a random per-process key in dev (signs users out on restart). |
| `MEMORA_DB` | Path to the SQLite database. Defaults to `~/memora-data/memora.db`. For durable data on Render, mount a persistent disk and point this at it (e.g. `/data/memora.db`). |
| `MEMORA_SECRET` | A fixed secret key. Set this to a long random string so sessions (logins) survive re-deploys instead of logging everyone out. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Enables AI flashcard generation (default model `gemini-2.5-flash`). Falls back to the offline heuristic engine when unset/unavailable. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Enables email delivery for the password-reset flow. When unset, the reset code is logged to the server output instead (for local testing). |
| `GOOGLE_CLIENT_ID` | Enables the **Sign in with Google** button in the login modal. See below for setup. |

## Durable data on Render (free) — neon.tech / Supabase

Render's **free** plan is ephemeral: it has **no persistent disk** (disks are premium-only), and Render's **free managed Postgres expires after 30 days** (then its data is wiped).

The reliable free option is to use a **free external PostgreSQL database** and point `DATABASE_URL` at it. Memora already switches to PostgreSQL automatically whenever `DATABASE_URL` is set — no code changes needed.

**neon.tech (recommended, free tier):**
1. Sign up at <https://neon.tech>, create a project (any region).
2. In **Connection details**, copy the **connection string** (starts with `postgresql://`).
3. In Render → your service → **Environment**, add:
   ```
   DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
   ```
4. Deploy. Your accounts, decks, cards, and progress now survive every redeploy.

**Supabase (alternative):**
1. Create a free project at <https://supabase.com>.
2. **Project Settings → Database → Connection string** (the **URI** for your pooler or direct connection).
3. Set the same `DATABASE_URL` env var on Render and redeploy.

> Keep `GEMINI_API_KEY` set too — it powers AI flashcards and AI quizzes.

## Google sign-in setup

1. Go to the **Google Cloud Console** → <https://console.cloud.google.com> and
   create (or select) a project.
2. **APIs & Services → OAuth consent screen.** Choose *External*, fill in the
   app name and your email, and *Save*. Add your email as a **test user** (or
   publish the app once you're happy).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   Choose *Web application*.
4. Under **Authorized JavaScript origins** add your app's origin, e.g.
   `http://localhost:5000`. (No redirect URI is needed for the ID-token flow.)
5. Copy the **Client ID** (it looks like
   `xxxx-xxxx.apps.googleusercontent.com`).
6. Put it in your `.env`:
   ```
   GOOGLE_CLIENT_ID=xxxx-xxxx.apps.googleusercontent.com
   ```
   Then restart `python app.py`. The **Sign in with Google** button will appear
   in the login modal.

Only the **Client ID** is required — this flow uses Google's ID-token
verification, so **no Client Secret** is needed.

> Note: If a test user is not set / the app is unapproved, Google may show a
> "Google hasn't verified this app" screen — that's expected for an in-development
> app. You can proceed past it, or add your Google account as a test user.

## Changelog

See [CHANGELOG.md](CHANGELOG.md), also viewable in-app via the "Changelog" link in the footer.

Port and database location are configurable via environment variables:

```bash
PORT=8080 MEMORA_DB=/path/to/memora.db python app.py
```

The database defaults to `~/memora-data/memora.db` (kept off the workspace/network mount so SQLite can lock it reliably).

## Project layout

```
memora/
  app.py            Flask routes, auth, generation, study, stats API
  db.py             SQLite schema + queries
  generator.py      flashcard generation (fallback/demo, AI-ready)
  static/
    index.html      app shell + modals
    style.css       all styling (light + dark)
    app.js          single-page app logic
  requirements.txt
```

## API overview

| Method & path | Purpose |
|---|---|
| `POST /api/auth/register`, `/api/auth/login` | create account / sign in → returns token |
| `GET /api/auth/me` | current user |
| `POST /api/generate` | generate flashcards (enforces the 1-free-card guest limit) |
| `GET/POST /api/decks` | list / create decks |
| `GET/PATCH/DELETE /api/decks/<id>` | view / rename+favorite / delete |
| `POST /api/decks/<id>/cards` | add a card |
| `PATCH/DELETE /api/cards/<id>` | edit / delete a card |
| `POST /api/decks/<id>/study` | record a study session |
| `GET /api/stats` | totals, accuracy, daily study time, streak |

The free-card limit works like this: an unauthenticated request with an `X-Guest-Id` header returns exactly **1** card the first time (and records usage), then returns `402 sign_in_required` on subsequent attempts. Once a user is signed in (`Authorization: Bearer <token>`), the full requested card count is returned.