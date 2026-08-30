# Changelog

All notable changes to Memora are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/). Current version: **12.6.0**.

## [12.6.0] - current

### Added
- **Import decks from Anki/Quizlet.** The My Decks page now has an **Import**
  button that opens a modal — paste one card per line and Memora turns them
  into a deck. Supports tab-separated pairs (Anki / Quizlet export), `Term:
  Definition`, `Term — Definition`, and `Term, Definition`.
- **Multiple-choice Quiz mode.** Each deck has a **Quiz** button. Memora shows
  the question with up to 4 answer choices (wrong answers are pulled from your
  other cards' backs), gives instant right/wrong feedback, and scores your
  run. Supports keyboard shortcuts: `1–4` to pick, `Enter` to advance.
- **Shuffle toggle in study mode.** A **🔀 Shuffle / In order** button in the
  study header lets you switch between a shuffled deck and the original order,
  so you never just memorize the sequence. (Shuffle stays on by default.)
- **Smarter test/worksheet flashcards.** Memora now recognizes graded tests and
  worksheets with a numbered or unnumbered **Question list** plus an **Answer
  Key** (e.g. an English grammar test). It pairs each question with its matching
  answer into clean flashcards, keeps fill-in-the-blank "________" prompts intact
  (answer goes on the back), and no longer wraps quoted sentences like
  "He don't like reading books." into "What is …".

### Changed
- **requirements.txt now includes `gunicorn`** (production WSGI server for
  Render). Render runs `gunicorn app:app` for a stable production deployment.

## [12.3.0] - previous

### Added
- **Upload PDFs in the generator.** You can now import `.pdf` files (not just
  `.txt`). Text is extracted server-side with `pypdf` (added to
  requirements.txt) and fed straight into the flashcard maker.

### Fixed
- **Deck delete button.** Reworked the delete confirmation to be self-contained
  so it always responds, and the delete action is instant (the server enforces
  the favourite-protection rule).

## [12.2.0] - previous

### Added
- **Sign in with Google.** The login/signup modal now offers a Google button
  (shown only once `GOOGLE_CLIENT_ID` is set in `.env`). Uses Google's ID-token
  flow — only the Client ID is needed, no Client Secret. See the README for the
  6-step setup.

### Changed
- **More landing-page particles.** The floating dots are denser (but still
tasteful) and still spread away from your cursor.

## [12.1.0] - previous

### Changed
- **Auto-definitions are richer.** The Term & Definition lookup now takes a
  little longer and prefers a fuller, more informative definition (still under
  a sensible cap) instead of the shortest match.
- **Deck limit**: you can save up to **25 decks** per account. The limit isn't
  advertised anywhere — it's only enforced if you try to save a 26th deck, at
  which point you'll be asked to delete one to make room.

## [12.0.0] - previous

### Added
- **Auto-definitions for Term & Definition cards.** When a term's back is a
  long prose sentence rather than a clean definition, Memora fetches a concise
  English definition from the public Datamuse API (no key required, runs
  locally). It's best-effort: if the word is unknown or the network is down,
  the original text is kept.
- **Deck controls on the dashboard** — each study-corner card now has Study and
  Delete buttons.

### Changed
- **You can no longer delete a favourited deck.** The delete button is disabled
  on favourited decks, and the server rejects the request until you unfavorite
  it first. (Deleting now also reports a real error message instead of falsely
  saying “Deck deleted”.)
- Generator label is now “(enter content or upload a .txt file)”.

## [11.0.0] - previous

### Changed
- **Study results now point to question numbers.** When you finish a deck (or
  revisit the deck page after a round), the summary tells you which numbered
  questions you missed (e.g. “question 2, 5, 9”) instead of repeating the full
  question text.
- **“Almost” answers show yellow** on the progress bar (previously they were
  red, same as “Didn’t Know”). “Knew It” stays green, “Didn’t Know” stays red.

## [10.0.0] - previous

### Changed
- **Number of cards is now a slider** (1–50) instead of preset buttons — drag
  it to pick exactly how many flashcards you want.
- **Study activity shows minutes, not seconds**, and each bar now shows a tooltip
  with your exact study time when you hover over it.
- **Changelog reads like plain language** instead of raw markdown — version
  badges, tidy headings, and readable bullet points.
- **Dashboard stat cards now follow the theme in dark mode** (they no longer
  stay black when clicked).

## [9.0.0] - previous

### Fixed
- **Subject & Library sort dropdowns now actually open.** The `open` class
  was toggled on the menu element while the CSS expected it on the wrapper, so
  the list never appeared.
- **Smart Review back navigation**: you can now reliably click “← Back to
  Deck” (or “My Decks” for cross-deck review). Smart Review didn't change the
  URL hash, so clicking back to the same deck hash fired no `hashchange` and
  left you stuck. Added `App.leaveStudy()` which re-routes even when the hash
  is unchanged.

### Changed
- Dashboard stat cards (**Total cards**, **Cards reviewed**, **Study streak**,
  **To review**) are now clickable: Total cards → Library, Cards reviewed &
  Study streak → Stats, To review → cross-deck Smart Review. Added hover lift
  and cursor feedback.

## [8.0.0] - previous

### Added
- Custom styled dropdowns for the **Subject** picker and the Library sort
  selector, replacing native `<select>` elements whose OS-rendered open menu
  had hard 90-degree corners. The open list now has rounded corners, shadow,
  and hover/active states that match the theme.
- Friendlier "No flashcards found" state when the notes are a request/command
  (e.g. "Make me a deck") rather than study material.

### Fixed
- Imperative/request sentences no longer produce junk flashcards like
  "What is Make?". The synthesizer now detects request openers ("make me",
  "please", "can you", "give me", …) and bare leading verbs, and skips them.

## [7.0.0] - previous

### Added
- **Spaced repetition (SM-2).** Cards are scheduled on an interval with an ease
  factor and a due date, replacing the old "2 correct answers = mastered"
  heuristic. A card is "mastered" once scheduled out to a 3+ day interval.
  New `GET /api/due` returns the user's cards due for review.
- **Password reset via email verification code.**
  - `POST /api/auth/forgot-password` generates and sends a 6-digit code.
  - `POST /api/auth/reset-password` verifies the code and sets a new password
    (revoking all existing sessions).
  - Codes are single-use and expire after 5 minutes; only the code's hash is
    stored. Real delivery uses SMTP (see `.env.example`); without SMTP the code
    is logged for local testing. A "Forgot password?" flow was added to the UI.
- **Stable session secret.** `MEMORA_SECRET` is read from env or persisted to
  `~/.memora-data/secret.key`, so users are not logged out on every restart.
- **Versioning.** App version (7.0.0) exposed via `/api/health`, `/api/version`,
  and shown in the footer.
- `GET /api/changelog` and an in-app "Changelog" modal (footer link).
- `.env` support (loads `KEY=VALUE` from a `.env` file) and `.env.example`.

### Changed
- Guest 1-free-card limit now enforced with a server-signed, HttpOnly,
  SameSite cookie (`memora_guest`) instead of a spoofable client-supplied
  `X-Guest-Id` header.
- `run.bat` / `run.sh` now use `python -m pip` so they work even when the bare
  `pip` command is not on PATH, and print a helpful message if Python is missing.
- Default Gemini model updated from deprecated `gemini-1.5-flash` to
  `gemini-2.5-flash`.
- Logout now revokes the session token server-side.

### Fixed
- Junk-card generation: the heuristic generator no longer re-parses structured
  Q/A, table, and bullet lines into bogus cards like "What is Question 2?".
- Free demo card quality: replaced the ugly "Key Concept: ..." synthesize step
  with a clean noun-phrase front (e.g. "What is Photosynthesis?").
- Cloze generation failing on sentences that end with a period.
- `test_backend.py` hardcoded Windows path.

### Security
- Rate limiting on `/api/generate`, `/api/auth/register`, `/api/auth/login`,
  `/api/auth/change-password`, `/api/auth/forgot-password`,
  `/api/auth/reset-password`.
- Password minimum length raised from 3 to 8 characters.
- New `POST /api/auth/change-password` endpoint (revokes all sessions).

## [0.1.0] - initial

### Added
- Turn notes into flashcards (heuristic + optional Gemini engine).
- Decks, cards, study mode, smart review, stats, light/dark theme.
- One-free-flashcard guest funnel (header-based).