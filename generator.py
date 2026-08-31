"""Flashcard generation for Memora.

Two-tier architecture:
1. OPTIONAL GEMINI / LLM ENGINE: If GEMINI_API_KEY is configured in the environment,
   queries Google Gemini API with a structured prompt requesting high-yield JSON
   flashcards. Falls back cleanly and silently on any error or missing key.

2. ENHANCED HEURISTIC ENGINE (Zero-dependency & Offline):
   - Structured Quiz / Flashcard dataset extraction (Q:/A:, Question:/Answer:, numbered lists).
   - Markdown Table extraction (| Term | Definition |).
   - Definition & Bullet list extraction (- **Term**: Definition, Term — Definition).
   - Natural language definition parsing (X is defined as Y, X refers to Y).
   - Sentence-anchored Cloze deletion generation.
   - Smart synthesis and deduplication.

The heuristic engine tracks which source lines/sentences it has already turned
into cards so structured content is never re-parsed into junk cards downstream.
"""

import json
import logging
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Gemini / LLM API Integration
# ---------------------------------------------------------------------------

# gemini-1.5-flash is deprecated; 2.5-flash is the current general-purpose model.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _generate_with_gemini(notes, subject, difficulty, number, style, api_key=None):
    """Generate flashcards using Gemini API if key is available.

    Returns list of dicts [{'front': ..., 'back': ...}] or None on failure.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    style_instruction = {
        "q&a": "Format each card with a clear question as 'front' and the direct factual answer as 'back'.",
        "term": "Format each card with the concept/term as 'front' and its concise definition as 'back'.",
        "cloze": "Format each card with a fill-in-the-blank sentence containing '______' as 'front' and the missing term as 'back'.",
        "mixed": "Provide a balanced mix of questions, definitions, and fill-in-the-blank cloze cards.",
    }.get(style, "Provide clear question-and-answer flashcards.")

    prompt_text = (
        f"You are an expert educator. Generate exactly {number} high-yield flashcards "
        f"from the provided study notes for subject '{subject}' at '{difficulty}' difficulty level.\n\n"
        f"Style requirement: {style_instruction}\n\n"
        f"Rules:\n"
        f"1. Rely strictly on facts mentioned in the notes.\n"
        f"2. Keep the 'front' punchy and 'back' concise and clear.\n"
        f"3. Return ONLY a valid JSON array of objects with keys 'front' and 'back'.\n"
        f"4. If the notes look like a test/worksheet with a numbered Question list and an "
        f"Answer Key, make ONE card per question: front = the question (keep any blank "
        f"like '________' exactly as-is), back = the answer.\n"
        f"5. If a 'front' is fill-in-the-blank, put only the missing word/phrase on the 'back'.\n"
        f"6. If a question is already complete (e.g. 'Correct the error: ...'), make the "
        f"corrected sentence the 'back'.\n"
        f"Example format: [ {{\"front\": \"What is X?\", \"back\": \"X is Y.\"}} ]\n\n"
        f"Study Notes:\n{notes}\n"
    )

    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json"
        }
    }

    try:
        data_bytes = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)

        candidates = result.get("candidates", [])
        if not candidates:
            return None

        content_parts = candidates[0].get("content", {}).get("parts", [])
        if not content_parts:
            return None

        raw_text = content_parts[0].get("text", "").strip()

        # Handle optional markdown code fences in response
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text).strip()

        cards_data = json.loads(raw_text)
        if isinstance(cards_data, list):
            valid_cards = []
            for item in cards_data:
                if isinstance(item, dict) and "front" in item and "back" in item:
                    f = str(item["front"]).strip()
                    b = str(item["back"]).strip()
                    if f and b:
                        valid_cards.append({"front": f, "back": b})
            if valid_cards:
                return valid_cards[:number]
    except Exception as exc:
        logger.warning("Gemini card generation fallback to heuristic: %s", exc)
        return None

    return None


def _generate_with_gemini_topic(subject, topic, difficulty, number, style, api_key=None):
    """Use Gemini to research a topic and write flashcards from its knowledge.

    This powers the "AI generate from a topic" mode (like the AI quiz): the
    user gives a topic instead of pasted notes, and the AI writes accurate
    cards about it. Returns a list of {front, back} or None.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    style_instruction = {
        "q&a": "Format each card with a clear question as 'front' and the direct factual answer as 'back'.",
        "term": "Format each card with the concept/term as 'front' and its concise definition as 'back'.",
        "cloze": "Format each card with a fill-in-the-blank sentence containing '______' as 'front' and the missing term as 'back'.",
        "mixed": "Provide a balanced mix of questions, definitions, and fill-in-the-blank cloze cards.",
    }.get(style, "Provide clear question-and-answer flashcards.")

    prompt_text = (
        f"You are an expert educator and researcher. Research your own knowledge to write "
        f"exactly {number} high-yield, factually accurate flashcards about the topic '{topic}' "
        f"for subject '{subject}' at '{difficulty}' difficulty level.\n\n"
        f"Style requirement: {style_instruction}\n\n"
        f"Rules:\n"
        f"1. Be specific and correct about '{topic}' — do not pad with generic facts from "
        f"outside the topic.\n"
        f"2. Keep the 'front' punchy and the 'back' concise and clear.\n"
        f"3. Cover the most important concepts, terms, and facts a student should know.\n"
        f"4. Return ONLY a valid JSON array of objects with keys 'front' and 'back'.\n"
        f"Example: [ {{\"front\": \"What is X?\", \"back\": \"X is Y.\"}} ]\n"
    )

    request_body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json"
        },
    }

    try:
        data_bytes = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data_bytes, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        candidates = result.get("candidates", [])
        if not candidates:
            return None
        raw_text = (candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "") or "").strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text).strip()
        cards_data = json.loads(raw_text)
        if isinstance(cards_data, list):
            valid = []
            for item in cards_data:
                if isinstance(item, dict) and item.get("front") and item.get("back"):
                    f = str(item["front"]).strip()
                    b = str(item["back"]).strip()
                    if f and b:
                        valid.append({"front": f, "back": b})
            if valid:
                return valid[:number]
    except Exception as exc:
        logger.warning("Gemini topic generation failed: %s", exc)
        return None
    return None


def generate_from_topic(subject, topic, difficulty="Medium", number=5, style="q&a"):
    """AI-generated flashcards on a topic (no pasted notes needed).

    Uses Gemini's research when a key is available. There is no offline
    fallback for arbitrary topics (we don't fabricate facts), so this returns
    [] without a key rather than inventing wrong answers.
    """
    topic = (topic or "").strip()
    if not topic:
        return []
    try:
        number = max(1, min(int(number), 50))
    except (ValueError, TypeError):
        number = 5
    llm = _generate_with_gemini_topic(subject, topic, difficulty, number, style)
    return (llm or [])[:number]


# ---------------------------------------------------------------------------
# 2. Heuristic Engine: Parsing & Patterns
# ---------------------------------------------------------------------------

_Q_START = re.compile(
    r"^\s*(?:"
    r"q\s*\d*\s*[:.)\-]|"
    r"question\s*\d*\s*[:.)\-]|"
    r"\*\*\s*q\s*\d*\s*[:.)\-]|"
    r"\d+\s*[.)\-]\s*"
    r")\s*",
    re.I,
)

_A_START = re.compile(
    r"^\s*(?:answer\s*\d*\s*[:.)\-]|ans\s*\d*\s*[:.)\-]|\*\*\s*a\s*\d*\s*[:.)\-]|[Aa]\s*[:.)\-]\s*)\s*",
    re.I,
)

_HASH_HEADER = re.compile(r"^\s*#{1,6}\s*")
_SEPARATOR = re.compile(r"^\s*(?:---+|\*\*\*+|===+|-{3,}|-+)\s*$")
_BULLET_PREFIX = re.compile(r"^\s*[-*•+]\s*")

# List / definition pattern: "- **Term**: Definition" or "Term — Definition" or "Term: Definition"
_LIST_DEF = re.compile(
    r"^\s*(?:[-*•+]\s*)?"
    r"(?:\*\*(?P<bterm>[^*]+)\*\*|(?P<pterm>[A-Za-z0-9][\w\s\-'\u2019]{1,45}))"
    r"\s*(?::|—|–|-|->|=>|=|::)\s+"
    r"(?P<desc>.+)$"
)

# Markdown table row pattern
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")

# Prose definition patterns
_DEF = re.compile(
    r"^(?P<subj>[A-Z][a-zA-Z0-9]*(?:\s+[a-zA-Z0-9][\w\-]*){0,4})"
    r"\s+(?P<verb>is defined as|refers to|is a type of|is known as|is considered|means|stands for|is|are|was|were)\s+"
    r"(?P<det>the|a|an|its|our|their|his|her|any|each)?\s*"
    r"(?P<val>.+?)\s*\.?\s*$"
)

_ACTION_VAL = re.compile(
    r"^(used|released|produced|formed|made|stored|found|located|transported|converted|known)\b",
    re.I,
)

_TITLE = re.compile(
    r"^(?!.*\b(is|are|was|were|means|refers|the|a|an|and|of|by|with|for|that|which)\b)"
    r"[A-Z0-9][^\n.!?]{1,39}$"
)

_IS_EQUATION = re.compile(r"(?:\d{1,3}[A-Za-z]|=\d|\d\s*\+\s*\d|=|→|←|⇄)")

_CLOZE = [
    (r"\bto\s+(?:produce|form|make|build|generate|create)\s+(?P<ans>[^.!?,]{2,80})\.?$",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\b(?:can\s+)?be\s+used\s+(?:by\s+[A-Za-z]+\s+)?for\s+(?P<ans>[^.!?]{2,80})\.?$",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\bis\s+(?:the|a|an|its|their)\s+(?P<ans>[A-Za-z][\w \-,.]*?)\s*$",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\bas\s+(?:a|an)\s+(?P<ans>[a-z][a-z\-]*)\b",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\b(?:called|known as|referred to as)\s+(?P<ans>[A-Z][A-Za-z]*(?:\s+[a-z][a-zA-Z]*)*)",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\bin\s+the\s+(?P<ans>[A-Za-z][a-z]*(?:\s+[a-z][a-z]*){0,3})\b",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\b(?:from|using|with)\s+(?P<ans>[^.!?,]{2,80})\s*\.?\s*$",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\b(?:responsible for|plays a key role in)\s+(?P<ans>[^.!?,]{2,80})\.?$",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
    (r"\b(?:composed of|consists of|made up of)\s+(?P<ans>[^.!?,]{2,80})\.?$",
     lambda s, m: s[:m.start("ans")] + "______" + s[m.end("ans"):]),
]


def _normalize(text):
    if not text:
        return ""
    return text.replace("\uFEFF", "").replace("\r\n", "\n").replace("\r", "\n")


def _clean_str(s):
    if not s:
        return ""
    s = re.sub(r"^\s*[-*•+]\s*", "", s)
    s = re.sub(r"\*\*+", "", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _strip_trailing_note(s):
    """Remove a balanced trailing parenthetical explanation from an answer.

    Handles nesting: "26 cm (2 * (8 + 5) = 26)" -> "26 cm",
    "x = 14 (23 - 9 = 14)" -> "x = 14", "A chef (or a cook)" -> "A chef".
    Returns the stripped string.
    """
    s = (s or "").rstrip()
    if not s.endswith(")"):
        return s
    depth = 0
    i = len(s) - 1
    start = None
    while i >= 0:
        c = s[i]
        if c == ")":
            depth += 1
        elif c == "(":
            depth -= 1
            if depth == 0:
                start = i
                break
        i -= 1
    if start is None:
        return s
    core = s[:start].strip()
    return core if core else s


def _is_heading(line):
    return bool(_TITLE.match(line.strip()))


# ---------------------------------------------------------------------------
# 3. Parsers for Structured Content
# ---------------------------------------------------------------------------

def _parse_tables(text):
    """Extract front/back from Markdown tables.

    Returns (pairs, used_indices): used_indices are the 0-based line numbers
    (into `text`) that produced cards, so callers avoid reprocessing them.
    """
    pairs = []
    used = set()
    lines = [(idx, ln.strip()) for idx, ln in enumerate(text.splitlines()) if ln.strip()]
    for idx, line in lines:
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Skip separator row like |---|---|
        if any(re.match(r"^:?-+:?$", c) for c in cells):
            continue
        if len(cells) >= 2:
            front, back = _clean_str(cells[0]), _clean_str(cells[1])
            if front.lower() in ("term", "concept", "question", "front", "item") and \
               back.lower() in ("definition", "description", "answer", "back", "meaning"):
                continue
            if len(front) >= 2 and len(back) >= 2:
                pairs.append((front, back))
                used.add(idx)
    return pairs, used


def _parse_bullet_definitions(text):
    """Extract bullet / colon / dash definitions.

    Returns (pairs, used_indices) so callers can avoid reprocessing used lines.
    """
    pairs = []
    used = set()
    for idx, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line or _SEPARATOR.match(line) or _HASH_HEADER.match(line):
            continue
        m = _LIST_DEF.match(line)
        if m:
            term = m.group("bterm") or m.group("pterm")
            desc = m.group("desc")
            if term and desc:
                t = _clean_str(term)
                d = _clean_str(desc)
                if len(t) >= 2 and len(d) >= 3 and len(t.split()) <= 6:
                    pairs.append((t, d))
                    used.add(idx)
    return pairs, used


def _parse_structured_qa(text):
    """Extract Q/A pairs from structured text.

    Returns (pairs, used_indices) where used_indices are the 0-based line
    indices (into `text`) consumed to make the cards.
    """
    lines = []
    for idx, raw in enumerate(text.splitlines()):
        ln = _clean_str(raw)
        if ln:
            lines.append((idx, ln))

    pairs = []
    used = set()
    pending_q = None  # (question_text, line_index)

    def flush_q():
        nonlocal pending_q
        pending_q = None

    for idx, line in lines:
        if _SEPARATOR.match(line):
            flush_q()
            continue
        if _HASH_HEADER.match(line):
            line = _HASH_HEADER.sub("", line).strip()
        if not line:
            continue

        qm = _Q_START.match(line)
        am = _A_START.match(line)

        if am and pending_q is not None:
            q, qidx = pending_q
            a = _A_START.sub("", line).strip()
            if a:
                pairs.append((q, a))
                used.add(qidx)
                used.add(idx)
            pending_q = None
            continue

        if qm and not am:
            flush_q()
            pending_q = (_Q_START.sub("", line).strip(), idx)
            continue

        if pending_q is not None and not _Q_START.match(line):
            if _is_question_line(line):
                # The next line is itself a question, not an answer — don't make
                # a wrong "QUESTION → QUESTION" card.
                pending_q = None
                pending_q = (line, idx)
                continue
            q, qidx = pending_q
            if line:
                pairs.append((q, line))
                used.add(qidx)
                used.add(idx)
            pending_q = None
            continue

        if line.endswith("?") and not _A_START.match(line) and not _Q_START.match(line):
            flush_q()
            pending_q = (line, idx)

    flush_q()
    return [(q, a) for (q, a) in pairs if q and a and len(q) > 2 and len(a) > 1], used


def _numbered_items(lines, start, end):
    """Return [(orig_line_idx, text)] for numbered items within lines[start:end].

    lines is a list of (idx, stripped_text). Numbered items look like "1. ...",
    "2) ...", "3- ...", etc.
    """
    items = []
    for orig_idx, ln in lines[start:end]:
        m = re.match(r"^\s*\d{1,3}\s*[.)\-]\s+(.+)$", ln)
        if m:
            items.append((orig_idx, m.group(1).strip()))
    return items


_CATEGORY_QUESTION = re.compile(
    r"^\s*(?:definition|question\s*\d*|synonym|antonym|sentence\s+completion|"
    r"contextual\s+meaning|word\s+association|prefixes?/roots?|root\s+word|"
    r"tone(?:\s*(?:&|and)\s*style)?|fill\s+(?:in\s+)?(?:the\s+blank)?|"
    r"complete(?:\s+the\s+sentence)?|grammar|vocabulary|spelling|pronunciation|matching)\s*[:.\-]",
    re.I,
)


def _is_question_line(ln):
    """True if a line is a real test question rather than an instruction/section.

    A question either has a fill-in-the-blank run of underscores, ends with a
    question mark, is a quoted sentence ("..."), is a vocabulary/worksheet
    category prompt ("Definition:", "Synonym:", "Antonym:", ...), or is a
    math/computational question that starts with a command word and contains a
    number or operator (e.g. "Calculate 84 - 39.", "Solve for x: x + 9 = 23.").
    """
    if re.search(r"_{3,}", ln):
        return True
    if ln.rstrip().endswith("?"):
        return True
    if ln.startswith('"') and ln.rstrip().endswith('"'):
        return True
    if _CATEGORY_QUESTION.match(ln):
        return True
    if (re.match(r"^\s*(?:calculate|solve|divide|evaluate|find|simplify|multiply|convert|compute|determine)\b", ln, re.I)
            and re.search(r"[\d=+*/×%^]", ln)):
        return True
    return False


def _parse_test_qa(text):
    """Pair a Question list with an Answer Key (worksheets / exams).

    Handles both numbered tests ("1. ...") and unnumbered ones where the
    questions are lines with blanks/"?"/quotes and the answers are given in
    order after an "Answer Key" header. Returns (pairs, used_indices).

    Example input:
        English Test
        Questions
        Fill in the blank with the past tense of the verb:
        She ___ (lose) her keys in the park yesterday.
        Answer Key:
        lost

    Produces {"front": "She ___ (lose) her keys...", "back": "lost"}.
    """
    lines = [(idx, ln.strip()) for idx, ln in enumerate(text.splitlines()) if ln.strip()]
    # Find the answer-section header (bare "Answer", "Answers", "Answer Key").
    # NOTE: a_pos is the position IN the `lines` list (not the original line number).
    a_pos = None
    for pos, (_, ln) in enumerate(lines):
        if re.match(r"^\s*(?:answer\s*key\b|answers?)\b", ln, re.I):
            a_pos = pos
            break
    if a_pos is None:
        return [], set()

    pre = lines[:a_pos]
    post = lines[a_pos + 1:]

    # Questions: prefer numbered items ("1. ..."), else recognized question lines.
    q_items = _numbered_items(lines, 0, a_pos)
    if len(q_items) < 2:
        q_items = [(idx, ln) for idx, ln in pre if _is_question_line(ln)]

    # Answers: numbered ("1. lost") or plain consecutive lines after the key.
    a_items = _numbered_items(lines, a_pos + 1, len(lines))
    if len(a_items) < len(q_items):
        a_items = [(idx, ln) for idx, ln in post
                    if not re.match(r"^\s*(?:answer|summary|correct|explanation|example|note|hint)", ln, re.I)]
    a_items = [(i, t) for i, t in a_items
               if not re.match(r"^\s*(?:questions?|part\s*\d+|answers?)\s*[:.]?\s*$", t, re.I)]

    pairs = []
    used = set()
    for (qidx, qtext), (aidx, atext) in zip(q_items, a_items):
        q = _clean_str(qtext)
        a = _clean_str(atext)
        # Drop a trailing (possibly nested) parenthetical explanation so the
        # card back stays concise: "x = 14 (23 - 9 = 14)" -> "x = 14".
        a = _strip_trailing_note(a)
        if q and a and q.lower() != a.lower():
            pairs.append((q, a))
            used.add(qidx)
            used.add(aidx)
    # Mark the whole test block (from the first question to the last answer) as
    # used, so leftover lines aren't re-parsed into junk prose cards downstream.
    if pairs:
        n = min(len(q_items), len(a_items))
        lo = q_items[0][0]
        hi = a_items[n - 1][0] if n else q_items[0][0]
        for orig_idx, _ln in lines:
            if lo <= orig_idx <= hi:
                used.add(orig_idx)
    return pairs, used


# ---------------------------------------------------------------------------
# 4. Prose / Sentence Processing & Card Builders
# ---------------------------------------------------------------------------

def _split_sentences(text):
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if _IS_EQUATION.search(line):
            out.append(("eq", line))
            continue
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip()
            if part and not _is_heading(part):
                out.append(("sent", part))
    return out


def _definition(sentence):
    m = _DEF.match(sentence)
    if not m:
        return None
    subj = m.group("subj").strip()
    det = (m.group("det") or "").strip()
    val = m.group("val").strip()
    if subj.lower().startswith(("the ", "a ", "an ", "most ", "the most ")):
        return None
    if len(subj.split()) > 5:
        return None
    if _ACTION_VAL.match(val) or re.match(r"^(released|produced|made|used|stored)\b", val, re.I):
        return None
    if len(val) > 250:
        return None
    back = ((det + " " + val) if det else val).strip()
    return subj, back


def _cloze(sentence):
    s = sentence
    for pattern, builder in _CLOZE:
        m = re.search(pattern, s)
        if not m:
            continue
        ans = m.group("ans").strip()
        ans = re.sub(r"[.…]+$", "", ans).strip()
        if not ans or len(ans) < 2 or len(ans) > 80:
            continue
        if len(ans) / max(len(s), 1) > 0.60:
            continue
        front = builder(s, m).strip()
        front = re.sub(r"\s+", " ", front)
        return front, ans
    return None


_VERBS = {"is", "are", "was", "were", "has", "have", "had", "do", "does", "did",
          "will", "would", "can", "could", "shall", "should", "may", "might", "must",
          "converts", "convert", "converting", "converted", "forms", "form", "formed", "forming",
          "makes", "make", "made", "releases", "release", "released", "uses", "use", "used",
          "contains", "contain", "contained", "stores", "store", "stored", "produces", "produce",
          "breaks", "breaks down", "carries", "carry", "controls", "control", "measures", "measure",
          "transports", "transport", "generates", "generate", "absorbs", "absorb", "reacts", "react",
          "speeds", "speed", "helps", "help", "regulates", "regulate", "regulating", "allows", "allow",
          "enables", "enable", "prevents", "prevent", "promotes", "promote", "inhibits", "inhibit",
          "acts", "act", "acts as", "increases", "increase", "decreases", "decrease", "catalyzes",
          "catalyze", "protects", "protect", "codes", "code", "encodes", "encode", "supports", "support",
          "boosts", "boost", "reduces", "reduce", "maintains", "maintain", "fights", "fight", "detects",
          "detect", "regulates the", "responds", "respond", "stimulates", "stimulate"}


# Imperative / request openers: these are commands, not study facts.
_REQUEST_OPENERS = (
    "make me", "give me", "tell me", "write me", "write", "create a", "create", "generate a",
    "generate", "build", "please", "can you", "could you", "would you", "help me", "explain",
    "define", "describe", "show me", "list", "convert", "turn", "design", "provide", "summarize",
    "come up", "come up with", "produce", "i want", "i need",
)


def _leading_term(text):
    """Pull a short noun-phrase term from the front of a sentence for synthesized cards.

    Returns "" for imperative/request sentences (e.g. "Make me a ... deck") or
    when the first word is a bare verb, so we never emit junk cards like
    "What is Make?". Stops at the first verb or clause boundary so we get e.g.
    "Photosynthesis" (not "Photosynthesis converts sunlight").
    """
    t = text.strip().lstrip("*#").strip()
    low_start = t.lower()
    for opener in _REQUEST_OPENERS:
        if low_start.startswith(opener):
            return ""
    m = re.match(r"^(the|a|an|this|these|those|some|any|its|their|our)\s+", t, re.I)
    if m:
        t = t[m.end():]
    tokens = t.split()
    if not tokens:
        return ""
    # A bare leading verb is an imperative/action, not a noun-phrase term.
    if tokens[0].strip(".,!?:;'").lower() in _VERBS:
        return ""
    out = []
    for i, w in enumerate(tokens):
        low = w.strip(".,!?:;'").lower()
        if low in _VERBS:
            break
        if i > 0 and w[0].isupper() and low not in ("a", "an", "the"):
            break  # a new capitalized word mid-phrase starts a new clause/term
        out.append(w.strip(".,!?:;'"))
        if len(out) >= 3:
            break
    if out:
        return " ".join(out)
    return tokens[0].strip(".,!?:;'")


def _build_card_from_pair(front, back, style):
    front = _clean_str(front)
    back = _clean_str(back)
    if not front or not back:
        return None

    # Question/command openers that already form a complete prompt and should
    # NOT be wrapped in "What is ..." (e.g. "Calculate 84 - 39.", "Solve for
    # x: ...", "Find the area of ...").
    _Q_OPENERS = ("what", "how", "why", "which", "where", "who", "when",
                  "describe", "explain", "calculate", "solve", "divide",
                  "evaluate", "find", "simplify", "multiply", "convert",
                  "compute", "determine", "identify", "state", "name",
                  "list", "give", "write", "define", "rewrite", "match")

    if style == "term":
        if front.endswith("?") or front.lower().startswith("what is "):
            # Invert question to term style if simple
            clean_term = re.sub(r"^what is\s+", "", front, flags=re.I).rstrip("?").strip()
            return {"front": clean_term or front, "back": back}
        return {"front": front, "back": back}
    elif style == "cloze":
        if "______" in front:
            return {"front": front, "back": back}
        return {"front": f"Fill in the blank: {front} is ______.", "back": back}
    elif style == "mixed":
        # Never wrap an already-formed cloze front in "What is ..."
        if "______" in front:
            return {"front": front, "back": back}
        if front.endswith("?") or front.lower().startswith(_Q_OPENERS) or '"' in front:
            return {"front": front, "back": back}
        return {"front": f"What is {front}?", "back": back}
    else:  # q&a default
        # Never wrap an already-formed cloze front in "What is ..."
        if "______" in front:
            return {"front": front, "back": back}
        if not front.endswith("?") and not front.lower().startswith(_Q_OPENERS) and '"' not in front:
            return {"front": f"What is {front}?", "back": back}
        return {"front": front, "back": back}


def _topic_from_notes(text, subject):
    for line in text.split("\n"):
        line = line.strip()
        if line and _is_heading(line):
            return line
    return subject or "the topic"


# ---------------------------------------------------------------------------
# 5. Master Generator
# ---------------------------------------------------------------------------

_DATAMUSE_URL = "https://api.datamuse.com/words?sp={term}&md=d&max=6"


def _fetch_definition(term, timeout=5):
    """Best-effort English definition lookup via the public Datamuse API.

    No API key required. Returns the fullest cleaned definition under a length
    cap (more informative for flashcards) or "" if the word is unknown / the
    network is down. Used to enrich Term & Definition cards.
    """
    term = (term or "").strip().lower()
    if not term or len(term.split()) != 1 or not re.match(r"^[a-z][a-z\-']*$", term):
        return ""
    try:
        url = _DATAMUSE_URL.format(term=urllib.parse.quote(term))
        req = urllib.request.Request(url, headers={"User-Agent": "Memora/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            return ""
        # Prefer an exact-word hit, then any entry that carries definitions.
        data = sorted(data, key=lambda x: (str(x.get("word")).lower() != term, 0 if x.get("defs") else 1))
        best = ""
        for entry in data:
            for d in (entry.get("defs") or []):
                parts = str(d).split("\t", 1)
                txt = _clean_str(parts[1] if len(parts) > 1 else parts[0])
                # Strip a leading parenthetical qualifier like "(biochemistry) ".
                txt = re.sub(r"^\([^)]*\)\s+", "", txt).strip()
                # Keep the fullest definition under a sensible flashcard cap.
                if txt and 10 <= len(txt) <= 240 and len(txt) > len(best):
                    best = txt
        return best[:240]
    except Exception:
        pass
    return ""


# Request detection: "make me a deck about X" / "a simple English vocabulary deck"
_REQUEST_VERB = re.compile(r"\b(?:create|make|build|generate|write|prepare|draft)\b", re.I)
_REQUEST_NOUN = re.compile(r"\b(?:flashcard\s+)?(?:deck|set|flashcards?|cards?)\b", re.I)
_TOPIC_AFTER = re.compile(r"\b(?:about|on|for|covering|of)\s+(.+?)\s*$", re.I)
_LEAD_FILLER = re.compile(
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?(?:create|make|generate|write|prepare|draft)\s+"
    r"(?:me\s+)?(?:a\s+|an\s+)?(?:simple|short|easy|new|fun|custom|basic|beginner)?\s*", re.I,
)


def _request_topic(notes):
    """If `notes` is a request like "make me a deck about X" (rather than real
    study material), return the topic X; otherwise return None.

    A request must (a) contain a command verb (create/make/generate...), (b)
    contain a deck noun (deck / cards / flashcards), and (c) be short. This
    keeps long pasted worksheets from ever being treated as a request.
    """
    first = (notes.strip().split("\n", 1)[0] or "").strip()
    if not first or len(first.split()) > 60:
        return None
    if not _REQUEST_VERB.search(first) or not _REQUEST_NOUN.search(first):
        return None

    m = _TOPIC_AFTER.search(first)
    if m:
        topic = m.group(1)
    else:
        # "a simple English vocabulary deck" -> "English vocabulary"
        dm = _REQUEST_NOUN.search(first)
        head = first[: dm.start()] if dm else first
        head = _LEAD_FILLER.sub("", head)
        topic = head.strip()
    topic = topic.strip(" .;:,\u2019\u201d\u2018\u201c").strip()
    if not topic or len(topic.split()) > 12:
        return None
    return topic


def generate(notes, subject="Other", difficulty="Medium", number=5, style="q&a"):
    """Generate up to `number` flashcards from notes.

    Tries the Gemini LLM first if GEMINI_API_KEY is available, then falls back
    to the heuristic engine. The heuristic engine processes source lines in
    priority order (structured Q&A -> tables -> bullet definitions -> prose) and
    never re-parses a line/sentence it has already turned into a card, so it
    does not emit junk cards like "What is Question 2?".
    """
    notes = _normalize(notes or "").strip()
    if not notes:
        return []

    try:
        number = max(1, min(int(number), 50))
    except (ValueError, TypeError):
        number = 5

    # 0. If the user pasted a request ("make me a deck about X") rather than
    #    real study material, ask the AI to build a deck on that topic.
    request_topic = _request_topic(notes)
    if request_topic:
        return generate_from_topic(subject, request_topic, difficulty, number, style)

    # 1. Attempt Gemini LLM if configured
    llm_cards = _generate_with_gemini(notes, subject, difficulty, number, style)
    if llm_cards:
        return llm_cards[:number]

    # 2. Heuristic Engine
    cards = []
    seen_fronts = set()

    def add_card(front, back):
        if not front or not back:
            return
        card = _build_card_from_pair(front, back, style)
        if not card:
            return
        key = card["front"].lower().strip()
        if key not in seen_fronts:
            seen_fronts.add(key)
            cards.append(card)

    def feed(pairs):
        for f, b in pairs:
            if len(cards) >= number:
                break
            add_card(f, b)

    def remove_lines(text, used_indices):
        if not used_indices:
            return text
        out = []
        for idx, ln in enumerate(text.split("\n")):
            if idx not in used_indices:
                out.append(ln)
        return "\n".join(out)

    remaining = notes
    topic = _topic_from_notes(notes, subject)

    # 2a. Test / worksheet pairing (numbered Question list + Answer Key). Run
    #     first so these lines aren't re-parsed into junk cards downstream.
    if len(cards) < number:
        test_pairs, used = _parse_test_qa(remaining)
        feed(test_pairs)
        remaining = remove_lines(remaining, used)

    # 2b. Structured Q&A
    qa_pairs, used = _parse_structured_qa(remaining)
    feed(qa_pairs)
    remaining = remove_lines(remaining, used)

    # 2c. Markdown tables
    if len(cards) < number:
        table_pairs, used = _parse_tables(remaining)
        feed(table_pairs)
        remaining = remove_lines(remaining, used)

    # 2d. Bullet / colon / dash definitions
    if len(cards) < number:
        bullet_pairs, used = _parse_bullet_definitions(remaining)
        feed(bullet_pairs)
        remaining = remove_lines(remaining, used)

    # 2d. Prose sentences (Definitions & Cloze). Track matched sentences so
    #     they aren't re-synthesized in 2e.
    used_sentences = set()
    if len(cards) < number:
        sentences = _split_sentences(remaining)
        for kind, text in sentences:
            if len(cards) >= number:
                break
            if kind == "eq":
                add_card(f"What is the equation for {topic}?", text)
                used_sentences.add(text)
                continue

            defi = _definition(text)
            if defi:
                subj, val = defi
                add_card(subj, val)
                used_sentences.add(text)
                continue

            cloze = _cloze(text)
            if cloze:
                cf, cb = cloze
                add_card(cf, cb)
                used_sentences.add(text)
                continue

    # 2e. Synthesize a clean term card from unmatched informative sentences.
    if len(cards) < number:
        sentences = _split_sentences(remaining)
        for kind, text in sentences:
            if len(cards) >= number:
                break
            if text in used_sentences or kind == "eq" or _is_heading(text):
                continue
            words = text.split()
            if len(words) < 5 or len(text) <= 25:
                continue
            term = _leading_term(text)
            if term:
                add_card(term, text)

    # 2f. Best-effort English enrichment for Term & Definition style. When a
    #     term card's back is a long prose sentence rather than a clean
    #     definition, fetch a concise one from the Datamuse API (no key needed).
    #     Graceful: if the network is down or the word is unknown, keep original.
    if style == "term":
        lookups = 0
        for card in cards:
            if lookups >= 4:
                break
            front = (card.get("front") or "").strip()
            if len(front.split()) != 1 or not re.match(r"^[A-Za-z][A-Za-z\-']*$", front):
                continue
            back = (card.get("back") or "").strip()
            if len(back) <= 70 or back.lower().rstrip(".") == front.lower():
                continue
            d = _fetch_definition(front)
            lookups += 1
            if d and len(d) < 220:
                card["back"] = d

    return cards[:number]


# ===========================================================================
# 5. Quiz generation (multiple-choice quizzes for the Quizzes section)
# ===========================================================================

# Fallback curated bank (used when Gemini is not configured/available).
_QUIZ_BANK = {
    "English": [
        {"question": "What is the opposite (antonym) of \"difficult\"?",
         "options": ["easy", "hard", "tall", "heavy"], "answer": "easy"},
        {"question": "What is the plural form of the noun \"child\"?",
         "options": ["childs", "children", "childes", "childrens"], "answer": "children"},
        {"question": "Which word is a verb?",
         "options": ["run", "easily", "slowly", "happy"], "answer": "run"},
        {"question": "Which sentence is correct?",
         "options": ["He don't like reading.", "He doesn't like reading.",
                      "He not like reading.", "He doesn't likes reading."],
         "answer": "He doesn't like reading."},
        {"question": "Fill in the blank: \"She ____ her keys yesterday.\"",
         "options": ["lose", "lost", "losing", "losted"], "answer": "lost"},
        {"question": "What is a synonym of \"happy\"?",
         "options": ["sad", "joyful", "angry", "tired"], "answer": "joyful"},
        {"question": "Which word is a noun?",
         "options": ["quickly", "dog", "run", "and"], "answer": "dog"},
        {"question": "Choose the correct spelling:",
         "options": ["receive", "recieve", "receve", "receeve"], "answer": "receive"},
    ],
    "Math": [
        {"question": "What is 12 + 28?", "options": ["40", "42", "50", "38"], "answer": "40"},
        {"question": "What is 7 × 8?", "options": ["54", "48", "56", "64"], "answer": "56"},
        {"question": "What is 144 ÷ 12?", "options": ["10", "11", "12", "14"], "answer": "12"},
        {"question": "Solve for x: x + 9 = 23.", "options": ["14", "32", "13", "15"], "answer": "14"},
        {"question": "What is 3 squared (3²)?", "options": ["6", "9", "8", "12"], "answer": "9"},
        {"question": "What is the square root of 64?", "options": ["6", "8", "7", "9"], "answer": "8"},
        {"question": "Simplify the fraction 12/9.", "options": ["2/3", "3/4", "5/6", "1/2"], "answer": "2/3"},
        {"question": "What is 15% of 80?", "options": ["10", "12", "15", "8"], "answer": "12"},
    ],
    "Science": [
        {"question": "Which organ pumps blood through the body?",
         "options": ["lungs", "heart", "liver", "kidney"], "answer": "heart"},
        {"question": "What gas do plants take in during photosynthesis?",
         "options": ["water", "carbon dioxide", "nitrogen", "hydrogen"], "answer": "carbon dioxide"},
        {"question": "What is the powerhouse of the cell?",
         "options": ["nucleus", "mitochondria", "ribosome", "membrane"], "answer": "mitochondria"},
        {"question": "Which planet is known as the Red Planet?",
         "options": ["Venus", "Mars", "Jupiter", "Saturn"], "answer": "Mars"},
        {"question": "What is the chemical formula for water?",
         "options": ["O2", "CO2", "H2O", "NaCl"], "answer": "H2O"},
        {"question": "Which force pulls objects toward the ground?",
         "options": ["magnetism", "gravity", "friction", "tension"], "answer": "gravity"},
        {"question": "What gas do plants release during photosynthesis?",
         "options": ["carbon dioxide", "oxygen", "nitrogen", "methane"], "answer": "oxygen"},
        {"question": "Which of these is a solid at room temperature?",
         "options": ["ice", "water", "steam", "oxygen"], "answer": "ice"},
    ],
}


def _generate_quiz_with_gemini(subject, topic, number, api_key=None):
    """Use Gemini to build a multiple-choice quiz.

    Returns a list of {question, options, answer} or None on failure / missing key.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    prompt = (
        f"You are an expert educator. Build a multiple-choice quiz for a {subject} student.\n"
        f"Topic: {topic or ('general ' + subject)}\n"
        f"Generate exactly {number} questions. Each question must have exactly 4 answer options "
        f"and one marked correct.\n"
        f"Return ONLY a valid JSON object with a key \"questions\" whose value is an array of "
        f"objects with keys \"question\", \"options\" (array of 4 strings), and \"answer\" "
        f"(the correct option text, which must be one of the options).\n"
        f"Rules: every fact must be correct for {subject}; order the 4 options randomly "
        f"(never always put the answer last); keep it clear and age-appropriate.\n"
        f"Example: {{\"questions\":[{{\"question\":\"What is 2+3?\","
        f"\"options\":[\"4\",\"5\",\"6\",\"7\"],\"answer\":\"5\"}}]}}"
    )
    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096,
                             "responseMimeType": "application/json"},
    }
    try:
        data_bytes = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        candidates = result.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None
        raw = parts[0].get("text", "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()
        data = json.loads(raw)
        questions = data.get("questions", [])
        out = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            question = str(q.get("question", "")).strip()
            options = [str(o).strip() for o in q.get("options", []) if str(o).strip()]
            answer = str(q.get("answer", "")).strip()
            if question and len(options) >= 4 and answer in options:
                out.append({"question": question, "options": options[:4], "answer": answer})
            if len(out) >= number:
                break
        return out[:number] if out else None
    except Exception as exc:
        logger.warning("Gemini quiz generation fallback to bank: %s", exc)
        return None


# Topic-specific banks so an offline quiz still honors the chosen topic
# (e.g. Science + "photosynthesis" returns photosynthesis questions).
_QUIZ_TOPICS = {
    "photosynthesis": {"subject": "Science", "questions": [
        {"question": "What is the main purpose of photosynthesis in plants?",
         "options": ["to turn sunlight into glucose and oxygen", "to absorb water from roots",
                      "to release heat", "to digest food"],
         "answer": "to turn sunlight into glucose and oxygen"},
        {"question": "Which organelle in plant cells carries out photosynthesis?",
         "options": ["mitochondria", "chloroplast", "nucleus", "ribosome"], "answer": "chloroplast"},
        {"question": "What gas do plants absorb during photosynthesis?",
         "options": ["oxygen", "carbon dioxide", "nitrogen", "hydrogen"], "answer": "carbon dioxide"},
        {"question": "What gas do plants release as a byproduct of photosynthesis?",
         "options": ["carbon dioxide", "oxygen", "nitrogen", "helium"], "answer": "oxygen"},
        {"question": "What is the main energy source that drives photosynthesis?",
         "options": ["sunlight", "heat", "water", "soil minerals"], "answer": "sunlight"},
        {"question": "What main product does photosynthesis create for the plant to store energy?",
         "options": ["protein", "glucose", "salt", "carbon"], "answer": "glucose"},
    ]},
    "cells": {"subject": "Science", "questions": [
        {"question": "What is the basic unit of life?",
         "options": ["atom", "cell", "organ", "tissue"], "answer": "cell"},
        {"question": "What is the 'powerhouse of the cell'?",
         "options": ["nucleus", "mitochondria", "chloroplast", "cell wall"], "answer": "mitochondria"},
        {"question": "Where is the cell's genetic material (DNA) stored?",
         "options": ["nucleus", "cytoplasm", "membrane", "ribosome"], "answer": "nucleus"},
        {"question": "Which part controls what enters and leaves the cell?",
         "options": ["cell wall", "cell membrane", "nucleus", "vacuole"], "answer": "cell membrane"},
    ]},
    "human body": {"subject": "Science", "questions": [
        {"question": "Which organ pumps blood around the body?",
         "options": ["lungs", "heart", "liver", "brain"], "answer": "heart"},
        {"question": "Which organ is mainly responsible for breathing?",
         "options": ["heart", "lungs", "kidneys", "stomach"], "answer": "lungs"},
        {"question": "Which organ controls the whole body?",
         "options": ["heart", "brain", "liver", "skin"], "answer": "brain"},
        {"question": "Which organ filters waste from the blood to make urine?",
         "options": ["kidneys", "stomach", "liver", "pancreas"], "answer": "kidneys"},
    ]},
    "fractions": {"subject": "Math", "questions": [
        {"question": "What is 1/2 + 1/2?", "options": ["1", "2", "1/4", "3/4"], "answer": "1"},
        {"question": "Simplify the fraction 4/8.", "options": ["1/2", "2/3", "1/4", "3/4"], "answer": "1/2"},
        {"question": "Which fraction is equivalent to 2/3?",
         "options": ["4/6", "3/4", "5/6", "1/2"], "answer": "4/6"},
        {"question": "What is 1/2 of 10?", "options": ["5", "2", "10", "20"], "answer": "5"},
    ]},
    "percentages": {"subject": "Math", "questions": [
        {"question": "What is 50% of 200?", "options": ["50", "100", "150", "25"], "answer": "100"},
        {"question": "Convert 0.5 to a percentage.", "options": ["5%", "50%", "0.5%", "15%"], "answer": "50%"},
        {"question": "What is 10% of 80?", "options": ["8", "10", "16", "4"], "answer": "8"},
        {"question": "Convert 1/4 to a percentage.", "options": ["40%", "25%", "4%", "14%"], "answer": "25%"},
    ]},
    "grammar": {"subject": "English", "questions": [
        {"question": "Which sentence is grammatically correct?",
         "options": ["She don't like it.", "She doesn't like it.", "She not like it.", "She doesn't likes it."],
         "answer": "She doesn't like it."},
        {"question": "What is the past tense of 'go'?",
         "options": ["goed", "went", "gone", "going"], "answer": "went"},
        {"question": "Choose the correct article: 'She ate ___ apple.'",
         "options": ["a", "an", "the"], "answer": "an"},
        {"question": "Which word is a noun?",
         "options": ["run", "quickly", "teacher", "beautiful"], "answer": "teacher"},
    ]},
    "vocabulary": {"subject": "English", "questions": [
        {"question": "What is a synonym of 'happy'?",
         "options": ["sad", "joyful", "angry", "tired"], "answer": "joyful"},
        {"question": "What is the opposite (antonym) of 'difficult'?",
         "options": ["hard", "easy", "heavy", "tall"], "answer": "easy"},
        {"question": "What is a synonym of 'big'?",
         "options": ["small", "large", "tiny", "short"], "answer": "large"},
        {"question": "What does 'ancient' mean?",
         "options": ["very old", "very new", "fast", "large"], "answer": "very old"},
    ]},
    "physics": {"subject": "Science", "questions": [
        {"question": "What is the SI unit of force?",
         "options": ["joule", "newton", "watt", "pascal"], "answer": "newton"},
        {"question": "What is the SI unit of energy?",
         "options": ["newton", "joule", "watt", "coulomb"], "answer": "joule"},
        {"question": "Which of these is a measure of speed?",
         "options": ["metres per second", "kilogram", "litre", "watt"], "answer": "metres per second"},
        {"question": "What keeps objects from floating off the ground?",
         "options": ["magnetism", "gravity", "friction", "inertia"], "answer": "gravity"},
        {"question": "What do we call a push or pull on an object?",
         "options": ["force", "mass", "density", "volume"], "answer": "force"},
        {"question": "What are the three common states of matter?",
         "options": ["solid, liquid, gas", "hot, cold, warm", "sky, sea, land", "metal, plastic, wood"], "answer": "solid, liquid, gas"},
    ]},
    "chemistry": {"subject": "Science", "questions": [
        {"question": "What is the chemical formula for water?",
         "options": ["H2O", "O2", "CO2", "NaCl"], "answer": "H2O"},
        {"question": "Which gas do humans need to breathe to live?",
         "options": ["carbon dioxide", "oxygen", "nitrogen", "helium"], "answer": "oxygen"},
        {"question": "What is the chemical symbol for the element oxygen?",
         "options": ["O", "Ox", "Oz", "N"], "answer": "O"},
        {"question": "What happens when iron rusts?",
         "options": ["it reacts with oxygen", "it turns into water", "it melts", "it evaporates"], "answer": "it reacts with oxygen"},
    ]},
    "astronomy": {"subject": "Science", "questions": [
        {"question": "Which planet is closest to the Sun?",
         "options": ["Venus", "Mercury", "Earth", "Mars"], "answer": "Mercury"},
        {"question": "What is a group of stars that forms a pattern in the sky called?",
         "options": ["galaxy", "constellation", "nebula", "comet"], "answer": "constellation"},
        {"question": "What is the Sun?",
         "options": ["a planet", "a star", "a moon", "an asteroid"], "answer": "a star"},
        {"question": "Which planet is known as the Red Planet?",
         "options": ["Jupiter", "Venus", "Mars", "Saturn"], "answer": "Mars"},
    ]},
    "botany": {"subject": "Science", "questions": [
        {"question": "What part of a plant takes in water and nutrients from the soil?",
         "options": ["leaf", "root", "stem", "flower"], "answer": "root"},
        {"question": "Which plant part makes food through photosynthesis?",
         "options": ["root", "stem", "leaf", "seed"], "answer": "leaf"},
        {"question": "What do plants use to attract pollinators?",
         "options": ["flowers", "thorns", "bark", "seeds only"], "answer": "flowers"},
        {"question": "What is the study of plants called?",
         "options": ["zoology", "botany", "geology", "chemistry"], "answer": "botany"},
    ]},
    "zoology": {"subject": "Science", "questions": [
        {"question": "What is the study of animals called?",
         "options": ["botany", "zoology", "astronomy", "geology"], "answer": "zoology"},
        {"question": "Which of these is a mammal?",
         "options": ["shark", "dolphin", "frog", "eagle"], "answer": "dolphin"},
        {"question": "What do you call animals that eat only meat?",
         "options": ["herbivores", "carnivores", "omnivores", "producers"], "answer": "carnivores"},
        {"question": "What is the scientific name for the group of animals with backbones?",
         "options": ["vertebrates", "invertebrates", "mollusks", "insects"], "answer": "vertebrates"},
    ]},
    "genetics": {"subject": "Science", "questions": [
        {"question": "What molecule carries genetic information?",
         "options": ["DNA", "protein", "glucose", "ATP"], "answer": "DNA"},
        {"question": "What are the units of heredity passed from parents to children?",
         "options": ["cells", "genes", "organs", "tissues"], "answer": "genes"},
        {"question": "How many chromosomes do humans normally have?",
         "options": ["23", "46", "48", "20"], "answer": "46"},
        {"question": "What is the study of heredity called?",
         "options": ["ecology", "genetics", "botany", "anatomy"], "answer": "genetics"},
    ]},
    "ecology": {"subject": "Science", "questions": [
        {"question": "What is the study of living things and their environment called?",
         "options": ["ecology", "geology", "medicine", "physics"], "answer": "ecology"},
        {"question": "What is a group of the same species in one area called?",
         "options": ["community", "population", "ecosystem", "biome"], "answer": "population"},
        {"question": "Which of these is a decomposer?",
         "options": ["fungus", "oak tree", "deer", "eagle"], "answer": "fungus"},
        {"question": "A food chain is made up of what?",
         "options": ["producers and consumers", "only plants", "only animals", "rocks and soil"], "answer": "producers and consumers"},
    ]},
    "medicine": {"subject": "Science", "questions": [
        {"question": "Which body system carries blood around the body?",
         "options": ["circulatory", "nervous", "digestive", "skeletal"], "answer": "circulatory"},
        {"question": "Which organ filters waste from the blood to make urine?",
         "options": ["kidney", "lung", "heart", "muscle"], "answer": "kidney"},
        {"question": "What kind of doctor treats bones and joints?",
         "options": ["orthopedist", "cardiologist", "dermatologist", "neurologist"], "answer": "orthopedist"},
        {"question": "Which organ produces insulin?",
         "options": ["liver", "pancreas", "stomach", "spleen"], "answer": "pancreas"},
    ]},
    "earth science": {"subject": "Science", "questions": [
        {"question": "What is the layer of gases around the Earth called?",
         "options": ["atmosphere", "hydrosphere", "lithosphere", "biosphere"], "answer": "atmosphere"},
        {"question": "What causes day and night?",
         "options": ["Earth's rotation", "Earth's orbit", "the moon", "clouds"], "answer": "Earth's rotation"},
        {"question": "What is molten rock that reaches the surface called?",
         "options": ["lava", "magma", "sand", "sediment"], "answer": "lava"},
        {"question": "Which of these is a renewable energy source?",
         "options": ["sunlight", "coal", "oil", "natural gas"], "answer": "sunlight"},
    ]},
    "geology": {"subject": "Science", "questions": [
        {"question": "What is the study of rocks and the solid Earth called?",
         "options": ["geology", "meteorology", "astronomy", "biology"], "answer": "geology"},
        {"question": "What are the three types of rocks?",
         "options": ["igneous, sedimentary, metamorphic", "sand, soft, brittle", "red, grey, black", "mountain, valley, plain"], "answer": "igneous, sedimentary, metamorphic"},
        {"question": "What is the hard outer layer of the Earth called?",
         "options": ["crust", "mantle", "core", "magma"], "answer": "crust"},
        {"question": "What is the innermost layer of the Earth?",
         "options": ["core", "crust", "mantle", "ocean"], "answer": "core"},
    ]},
}


def _subject_bank(subject):
    """Return the general question bank for a subject."""
    return list(_QUIZ_BANK.get(subject) or _QUIZ_BANK.get(subject.capitalize()) or _QUIZ_BANK.get("Science"))


def _pick_topic_bank(subject, topic):
    """Return a curated topic-specific bank for subject+topic, or None.

    Matching is lenient so the user's topic is honored: exact match, substring,
    or any single-word overlap (e.g. topic "photosynthesis process" matches the
    photosynthesis bank)."""
    if not topic:
        return None
    tl = (topic or "").lower().strip()
    if not tl:
        return None
    subj = subject.lower()
    words = [w for w in tl.split() if len(w) > 2]
    for key, spec in _QUIZ_TOPICS.items():
        if spec["subject"].lower() != subj:
            continue
        kl = key.lower()
        if kl == tl or kl in tl or any(w == kl for w in words):
            return list(spec["questions"])
    return None


def _dedupe_questions(qs):
    """Drop duplicate questions (case-insensitive), keeping first occurrence."""
    seen = set()
    out = []
    for q in qs:
        key = (q.get("question") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def generate_quiz(subject="Science", topic="", number=5):
    """Build a multiple-choice quiz.

    Tries the Gemini engine first (up to ~45s), then falls back to a curated
    built-in bank that honors the requested subject and topic. Never repeats a
    question and returns up to `number` distinct questions.
    """
    subject = (subject or "Science").strip()
    try:
        number = max(3, min(int(number), 10))
    except (ValueError, TypeError):
        number = 5

    llm_quiz = _generate_quiz_with_gemini(subject, topic, number)
    if llm_quiz:
        return _dedupe_questions(llm_quiz)[:number]

    # Offline fallback: lead with topic-specific questions, then fill in with
    # general subject questions — always distinct and capped at `number`.
    topic_qs = _dedupe_questions(_pick_topic_bank(subject, topic) or [])
    general_qs = _dedupe_questions(_subject_bank(subject))
    sel = list(topic_qs)
    for g in general_qs:
        if len(sel) >= number:
            break
        if not any(g.get("question", "").strip().lower() == q.get("question", "").strip().lower() for q in sel):
            sel.append(g)
    random.shuffle(sel)
    return [dict(q) for q in sel[:min(number, len(sel))]]