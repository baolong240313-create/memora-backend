/* ================= Memora app ================= */
(function () {
  "use strict";

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  const state = {
    token: localStorage.getItem("memora_token") || null,
    user: JSON.parse(localStorage.getItem("memora_user") || "null"),
    guestId: localStorage.getItem("memora_guest_id") || (function () {
      const g = "g-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem("memora_guest_id", g);
      return g;
    })(),
    pendingGen: null,
  };

  /* ---------------- cleanup handlers ---------------- */
  let cleanupHeroParticles = null;
  let cleanupStudyMode = null;

  function runCleanups() {
    if (cleanupHeroParticles) {
      cleanupHeroParticles();
      cleanupHeroParticles = null;
    }
    if (cleanupStudyMode) {
      cleanupStudyMode();
      cleanupStudyMode = null;
    }
  }

  /* ---------------- api ---------------- */
  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    if (state.token) headers["Authorization"] = "Bearer " + state.token;
    else headers["X-Guest-Id"] = state.guestId;
    const res = await fetch("/api" + path, {
      ...opts,
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (e) {}
    return { ok: res.ok, status: res.status, data };
  }

  function toast(msg, type = "") {
    const el = document.createElement("div");
    el.className = "toast " + type;
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, 2600);
    setTimeout(() => el.remove(), 3000);
  }
  function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function formatTime(sec) {
    sec = sec || 0;
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return (h ? h + "h " : "") + m + "m";
  }
  function loaderHtml(txt) {
    return `<div class="loader-wrap"><div class="spinner"></div><div class="loader-text">${txt || "Working…"}</div></div>`;
  }
  function navigate(hash) { location.hash = hash; }

  /* ---------------- nav / theme ---------------- */
  function renderNav() {
    const links = $("#navLinks");
    links.innerHTML = state.user
      ? `<a href="#/dashboard">Dashboard</a><a href="#/generator">Create</a><a href="#/library">My Decks</a><a href="#/quizzes">Quizzes</a><a href="#/stats">Stats</a>`
      : `<a href="#/generator">Create Flashcards</a>`;
    $$("#navLinks a").forEach(a => { a.classList.toggle("active", location.hash.startsWith(a.getAttribute("href"))); });
    const nu = $("#navUser");
    if (state.user) {
      const initials = (state.user.name || "U").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
      nu.innerHTML = `<div style="display:flex;align-items:center;gap:10px">
        <div class="avatar" title="${escapeHtml(state.user.email)}">${initials}</div>
        <button class="btn btn-ghost" id="logoutBtn">Sign out</button></div>`;
      $("#logoutBtn").onclick = async () => {
        await api("/auth/logout", { method: "POST" });
        state.token = null; state.user = null;
        localStorage.removeItem("memora_token"); localStorage.removeItem("memora_user");
        renderNav(); navigate("#/landing"); toast("Signed out");
      };
    } else {
      nu.innerHTML = `<button class="btn btn-primary" onclick="App.openAuth()">Sign In</button>`;
    }
  }
  function initTheme() {
    const saved = localStorage.getItem("memora_theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    paintTheme();
    $("#themeToggle").onclick = () => {
      const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", cur);
      localStorage.setItem("memora_theme", cur);
      paintTheme();
    };
  }
  function paintTheme() {
    $("#themeToggle").textContent = document.documentElement.getAttribute("data-theme") === "dark" ? "☀️" : "🌙";
  }

  /* ---------------- router ---------------- */
  const app = $("#app");
  const route = () => router();
  window.addEventListener("hashchange", router);

  async function router() {
    runCleanups();
    renderNav();
    const h = location.hash || "#/dashboard";
    if (state.user) {
      if (h === "#/landing" || h === "") navigate("#/dashboard");
      if (h === "#/dashboard") return renderDashboard();
      if (h === "#/generator") return renderGenerator();
      if (h === "#/library") return renderLibrary();
      if (h === "#/stats") return renderStats();
      if (h.startsWith("#/deck/")) return renderDeck(+h.split("/")[2]);
      if (h.startsWith("#/study/")) return renderStudy(+h.split("/")[2]);
      if (h === "#/review") return renderReview();
      if (h === "#/quizzes") return renderQuizzes();
      return renderDashboard();
    }
    // guest / signed-out
    if (h === "#/generator") return renderGenerator();
    if (h === "#/library" || h === "#/stats" || h.startsWith("#/deck/") || h.startsWith("#/study/")) {
      return renderAuthGate();
    }
    return renderLanding();
  }

  /* ---------------- auth modal ---------------- */
  let authMode = "login";
  let onAuthDone = null;
  function openAuth(sub, freeNote, onDone) {
    authMode = "login"; onAuthDone = onDone || null;
    $("#authModal").classList.remove("hidden");
    $("#authError").style.display = "none";
    $("#authSub").textContent = sub || "Sign in to keep studying.";
    const fn = $("#authFreeNote");
    if (freeNote) { fn.classList.remove("hidden"); fn.querySelector("span").textContent = freeNote; }
    else fn.classList.add("hidden");
    setAuthMode("login");
    setTimeout(() => $("#authEmail").focus(), 60);
  }
  function setAuthMode(m) {
    authMode = m;
    $("#tabLogin").classList.toggle("active", m === "login");
    $("#tabSignup").classList.toggle("active", m === "signup");
    $("#nameField").classList.toggle("hidden", m !== "signup");
    $("#authTitle").textContent = m === "login" ? "Welcome back" : "Create your account";
    $("#authSubmit").textContent = m === "login" ? "Sign In" : "Create Account";
  }
  function initAuthModal() {
    $("#authClose").onclick = () => $("#authModal").classList.add("hidden");
    $("#authModal").addEventListener("click", e => { if (e.target.id === "authModal") $("#authModal").classList.add("hidden"); });
    $("#tabLogin").onclick = () => setAuthMode("login");
    $("#tabSignup").onclick = () => setAuthMode("signup");
    $("#authForm").addEventListener("submit", async e => {
      e.preventDefault();
      const email = $("#authEmail").value.trim(), pass = $("#authPass").value, name = $("#authName").value.trim();
      const err = $("#authError"); err.style.display = "none";
      const btn = $("#authSubmit"); btn.disabled = true;
      const ep = authMode === "signup" ? "/auth/register" : "/auth/login";
      const { ok, data } = await api(ep, { method: "POST", body: { email, password: pass, name } });
      btn.disabled = false;
      if (!ok) { err.textContent = data.error || "Something went wrong."; err.style.display = "block"; return; }
      finalizeAuth(data, authMode === "signup" ? "Account created! Welcome 🎉" : "Signed in! 👋");
    });

    /* ---- Google sign-in (only when GOOGLE_CLIENT_ID is configured) ---- */
    async function loadGoogle() {
      const wrap = $("#googleAuth");
      if (!wrap) return;
      let cid = "";
      try { const { data } = await api("/config"); cid = (data && data.google_client_id) || ""; } catch (e) {}
      if (!cid) return;
      wrap.classList.remove("hidden");
      if (window.google && google.accounts) { initGoogleBtn(cid); return; }
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client";
      s.async = true;
      s.onload = () => initGoogleBtn(cid);
      document.head.appendChild(s);
    }
    function initGoogleBtn(cid) {
      if (!window.google || !google.accounts) return;
      google.accounts.id.initialize({ client_id: cid, callback: handleGoogleCredential, auto_select: false });
      google.accounts.id.renderButton($("#googleButton"), { theme: "outline", size: "large", shape: "pill", text: "continue_with" });
    }
    async function handleGoogleCredential(resp) {
      if (!resp || !resp.credential) { toast("Google sign-in failed.", "error"); return; }
      const { ok, data } = await api("/auth/google", { method: "POST", body: { credential: resp.credential } });
      if (!ok) { toast(data.message || data.error || "Google sign-in failed.", "error"); return; }
      finalizeAuth(data, "Signed in with Google! 👋");
    }

    function finalizeAuth(data, greeting) {
      state.token = data.token; state.user = data.user;
      localStorage.setItem("memora_token", data.token);
      localStorage.setItem("memora_user", JSON.stringify(data.user));
      $("#authModal").classList.add("hidden");
      renderNav();
      toast(greeting || "Signed in! 👋");
      const done = onAuthDone; onAuthDone = null;
      if (done) done(); else route();
    }

    /* ---- password reset flow (email verification code) ---- */
    const resetPanel = $("#resetPanel");
    const resetEmail = $("#resetEmail"), resetCode = $("#resetCode"), resetNewPass = $("#resetNewPass");
    const resetCodeField = $("#resetCodeField"), resetNewField = $("#resetNewField");
    const resetSendBtn = $("#resetSendBtn"), resetSubmitBtn = $("#resetSubmitBtn");
    const authTitle = $("#authTitle"), authSub = $("#authSub");

    function showResetMode(show) {
      $("#authForm").classList.toggle("hidden", show);
      resetPanel.classList.toggle("hidden", !show);
      if (show) {
        authTitle.textContent = "Reset your password";
        authSub.textContent = "Enter your email to receive a verification code.";
      } else {
        authTitle.textContent = authMode === "login" ? "Welcome back" : "Create your account";
        authSub.textContent = "Sign in to keep studying.";
      }
    }
    $("#forgotLink").onclick = () => {
      showResetMode(true);
      resetCodeField.style.display = "none"; resetNewField.style.display = "none";
      resetSendBtn.classList.remove("hidden"); resetSubmitBtn.classList.add("hidden");
      resetCode.value = ""; resetNewPass.value = "";
    };
    resetSendBtn.onclick = async () => {
      const err = $("#authError"); err.style.display = "none";
      const email = resetEmail.value.trim();
      if (!email) { err.textContent = "Enter your email address."; err.style.display = "block"; return; }
      const { ok } = await api("/auth/forgot-password", { method: "POST", body: { email } });
      if (!ok) { err.textContent = "Something went wrong."; err.style.display = "block"; return; }
      resetCodeField.style.display = ""; resetNewField.style.display = "";
      resetSendBtn.classList.add("hidden"); resetSubmitBtn.classList.remove("hidden");
      toast("Reset code sent to your email 📬");
    };
    resetSubmitBtn.onclick = async () => {
      const err = $("#authError"); err.style.display = "none";
      const body = { email: resetEmail.value.trim(), code: resetCode.value.trim(), new_password: resetNewPass.value };
      if (!body.email || !body.code || !body.new_password) { err.textContent = "Fill in all fields."; err.style.display = "block"; return; }
      const { ok, data } = await api("/auth/reset-password", { method: "POST", body });
      if (!ok) { err.textContent = data.error || "Couldn't reset password."; err.style.display = "block"; return; }
      resetPanel.classList.add("hidden"); $("#authForm").classList.remove("hidden");
      setAuthMode("login"); $("#authModal").classList.add("hidden");
      toast("Password reset — sign in with your new password ✅");
    };
    $("#resetBackLink").onclick = () => {
      resetPanel.classList.add("hidden"); $("#authForm").classList.remove("hidden");
      setAuthMode(authMode);
    };

    loadGoogle();
  }

  /* ---------------- changelog ---------------- */
  function inlineMd(t) {
    return (t || "")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }
  function renderChangelog(md) {
    const lines = md.split("\n");
    let html = "<div class='cl-intro'>Here’s what’s new in Memora — a friendlier recap of each release.</div>";
    for (const raw of lines) {
      const line = raw.trim();
      if (line.startsWith("## ")) {
        const rest = line.slice(3);
        const m = rest.match(/^\[([^\]]+)\]/);
        const badge = m ? `<span class="cl-badge">v${m[1]}</span>` : "";
        const label = m ? rest.slice(m[0].length).replace(/^[-–—:]\s*/, "").trim() : rest;
        html += `<div class="cl-version">${badge}<span>${inlineMd(label) || "Release"}</span></div>`;
      } else if (line.startsWith("### ")) {
        html += `<div class="cl-section">${inlineMd(line.slice(4))}</div>`;
      } else if (line.startsWith("- ") || line.startsWith("* ")) {
        html += `<div class="cl-item"><span class="cl-dot"></span>${inlineMd(line.slice(2))}</div>`;
      } else if (line.startsWith("#")) {
        // skip the top-level heading/keep-a-changelog boilerplate
      } else if (line) {
        html += `<div class="cl-note">${inlineMd(line)}</div>`;
      }
    }
    return html;
  }
  function initChangelog() {
    $("#changelogLink").onclick = async (e) => {
      e.preventDefault();
      const { data } = await api("/changelog");
      $("#changelogBody").innerHTML = renderChangelog(data.changelog || "");
      $("#changelogModal").classList.remove("hidden");
    };
    $("#changelogClose").onclick = () => $("#changelogModal").classList.add("hidden");
    $("#changelogModal").addEventListener("click", e => {
      if (e.target.id === "changelogModal") $("#changelogModal").classList.add("hidden");
    });
  }

  /* ---------------- confirm ---------------- */
  let confirmAction = null;
  function askConfirm(title, msg, okLabel, fn) {
    const modal = $("#confirmModal"), ok = $("#confirmOk"), cancel = $("#confirmCancel");
    // Bind fresh handlers on every call so the modal always works even if
    // boot-time binding was skipped or an error occurred.
    const hide = () => modal.classList.add("hidden");
    ok.onclick = () => { hide(); const f = confirmAction; confirmAction = null; f && f(); };
    cancel.onclick = () => { hide(); confirmAction = null; };
    confirmAction = fn;
    $("#confirmTitle").textContent = title;
    $("#confirmMsg").textContent = msg;
    ok.textContent = okLabel || "Delete";
    modal.classList.remove("hidden");
  }
  function initConfirm() {
    const modal = $("#confirmModal");
    modal.addEventListener("click", e => { if (e.target.id === "confirmModal") modal.classList.add("hidden"); });
  }

  /* ================= IMPORT DECK (Anki / Quizlet) ================= */
  function parseImport(text) {
    // Turn pasted lines like "Term⇥Definition" / "Term: Definition" /
    // "Term — Definition" / "Term, Definition" into {front, back} pairs.
    const cards = [];
    const lines = (text || "").split(/\r?\n/);
    for (let line of lines) {
      line = line.trim();
      if (!line) continue;
      // Skip obvious header rows (e.g. "Term⇥Definition").
      if (/^(term|front|question|concept)\s*[:>\t]\s*(definition|answer|back|meaning)$/i.test(line)) continue;
      let front = "", back = "";
      if (line.indexOf("\t") !== -1) {
        const parts = line.split("\t");
        front = parts[0].trim();
        back = parts.slice(1).join(" ").trim();
      } else {
        let m = line.match(/^(.{1,160}?)\s*[:：]\s+(.+)$/);
        if (m) { front = m[1].trim(); back = m[2].trim(); }
        else {
          m = line.match(/^(.{1,160}?)\s*[—–-]\s+(.+)$/);
          if (m) { front = m[1].trim(); back = m[2].trim(); }
          else {
            m = line.match(/^(.{1,160}?),\s*(.+)$/);
            if (m) { front = m[1].trim(); back = m[2].trim(); }
          }
        }
      }
      if (front && back && back !== front) cards.push({ front, back, style: "term" });
    }
    return cards;
  }
  // Make sure the import modal exists (it normally lives in index.html, but we
  // build it from JS too so Import always works even if a stale page is loaded).
  function ensureImportModal() {
    if ($("#importModal")) return;
    const wrap = document.createElement("div");
    wrap.className = "modal-overlay hidden";
    wrap.id = "importModal";
    wrap.innerHTML =
      `<div class="modal modal-wide">
        <button class="close" id="importClose">✕</button>
        <h2>Import a deck</h2>
        <p class="m-sub">Paste your cards below — one per line — and Memora will turn them into a deck.</p>
        <div class="imp-formats"><b>Supported formats</b>
          <div>Term&nbsp;⇥&nbsp;Definition &nbsp;(tab, like Anki/Quizlet export)</div>
          <div>Term: Definition &nbsp;·&nbsp; Term — Definition &nbsp;·&nbsp; Term, Definition</div></div>
        <div class="field"><label>Deck name</label><input type="text" id="impName" placeholder="e.g. Biology — Cells" /></div>
        <div class="field"><label>Your cards</label><textarea id="impText" placeholder="Mitochondria\tThe powerhouse of the cell\nPhotosynthesis\tTurns sunlight into chemical energy"></textarea>
          <div class="char-count" id="impCount">0 cards</div></div>
        <div class="error" id="impError"></div>
        <button class="btn btn-primary btn-block btn-lg" id="impCreateBtn">📥 Create deck</button>
      </div>`;
    document.body.appendChild(wrap);
    initImport();
  }
  function openImport() {
    ensureImportModal();
    $("#impName").value = "";
    $("#impText").value = "";
    const err = $("#impError"); err.style.display = "none";
    updateImpCount();
    $("#importModal").classList.remove("hidden");
    setTimeout(() => $("#impText").focus(), 60);
  }
  function updateImpCount() {
    const n = parseImport($("#impText").value).length;
    $("#impCount").textContent = n + " card" + (n === 1 ? "" : "s") + " found";
  }
  async function createImportDeck() {
    const err = $("#impError"); err.style.display = "none";
    const name = $("#impName").value.trim();
    const cards = parseImport($("#impText").value);
    if (!cards.length) { err.textContent = "Couldn't find any cards yet. Put one card per line, like: Term ⇥ Definition."; err.style.display = "block"; return; }
    if (!name) { err.textContent = "Give your deck a name first."; err.style.display = "block"; return; }
    const btn = $("#impCreateBtn"); btn.disabled = true;
    const { ok, status, data } = await api("/decks", { method: "POST", body: { name, subject: "Other", cards } });
    btn.disabled = false;
    if (!ok) {
      if (status === 403 && data.error === "deck_limit") { toast(data.message || "Deck limit reached.", "error"); return; }
      err.textContent = data.error || "Couldn't create the deck."; err.style.display = "block"; return;
    }
    $("#importModal").classList.add("hidden");
    toast("Imported " + cards.length + " card" + (cards.length === 1 ? "" : "s") + " ✅", "success");
    navigate("#/deck/" + data.deck.id);
  }
  function initImport() {
    const close = $("#importClose"), modal = $("#importModal"),
          text = $("#impText"), create = $("#impCreateBtn");
    if (!modal) return;
    if (close) close.onclick = () => modal.classList.add("hidden");
    modal.addEventListener("click", e => { if (e.target.id === "importModal") modal.classList.add("hidden"); });
    if (text) text.addEventListener("input", updateImpCount);
    if (create) create.onclick = createImportDeck;
  }

  /* ================= PARTICLES ================= */
  function initHeroParticles() {
    if (cleanupHeroParticles) {
      cleanupHeroParticles();
      cleanupHeroParticles = null;
    }
    const canvas = $("#heroParticles");
    if (!canvas || !canvas.parentElement) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId = null;
    let isRunning = true;
    const parent = canvas.parentElement;

    let width = (canvas.width = parent.offsetWidth || window.innerWidth);
    let height = (canvas.height = parent.offsetHeight || 420);

    const onResize = () => {
      if (!canvas || !canvas.isConnected || !canvas.parentElement) return;
      width = canvas.width = canvas.parentElement.offsetWidth || window.innerWidth;
      height = canvas.height = canvas.parentElement.offsetHeight || 420;
    };
    window.addEventListener("resize", onResize, { passive: true });

    const mouse = { x: -1000, y: -1000, radius: 140 };
    const onMouseMove = e => {
      if (!canvas.isConnected) return;
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    };
    const onMouseLeave = () => {
      mouse.x = -1000;
      mouse.y = -1000;
    };

    parent.addEventListener("mousemove", onMouseMove, { passive: true });
    parent.addEventListener("mouseleave", onMouseLeave, { passive: true });

    const count = Math.min(72, Math.max(42, Math.floor((width * height) / 6500)));
    const particles = [];
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.7,
        vy: (Math.random() - 0.5) * 0.7,
        size: Math.random() * 2 + 1.5,
        baseAlpha: Math.random() * 0.35 + 0.25,
      });
    }

    function animate() {
      if (!isRunning || !canvas.isConnected) return;
      ctx.clearRect(0, 0, width, height);

      const isDark = document.documentElement.getAttribute("data-theme") === "dark";
      const dotR = isDark ? 166 : 108;
      const dotG = isDark ? 171 : 92;
      const dotB = isDark ? 245 : 231;

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        // mouse spread repulsion
        const dx = p.x - mouse.x;
        const dy = p.y - mouse.y;
        const distSq = dx * dx + dy * dy;
        const radiusSq = mouse.radius * mouse.radius;
        if (distSq < radiusSq && distSq > 0) {
          const dist = Math.sqrt(distSq);
          const force = (mouse.radius - dist) / mouse.radius;
          p.x += (dx / dist) * force * 3.5;
          p.y += (dy / dist) * force * 3.5;
        }

        p.x += p.vx;
        p.y += p.vy;

        if (p.x < -10) p.x = width + 10;
        else if (p.x > width + 10) p.x = -10;
        if (p.y < -10) p.y = height + 10;
        else if (p.y > height + 10) p.y = -10;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${dotR}, ${dotG}, ${dotB}, ${p.baseAlpha})`;
        ctx.fill();

        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j];
          const cdx = p.x - p2.x;
          const cdy = p.y - p2.y;
          const cdistSq = cdx * cdx + cdy * cdy;
          if (cdistSq < 9025) { // 95^2
            const cdist = Math.sqrt(cdistSq);
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p2.x, p2.y);
            const lineAlpha = (1 - cdist / 95) * 0.16 * (isDark ? 1 : 0.8);
            ctx.strokeStyle = `rgba(${dotR}, ${dotG}, ${dotB}, ${lineAlpha})`;
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        }
      }

      animId = requestAnimationFrame(animate);
    }
    animId = requestAnimationFrame(animate);

    cleanupHeroParticles = () => {
      isRunning = false;
      if (animId) cancelAnimationFrame(animId);
      window.removeEventListener("resize", onResize);
      if (parent) {
        parent.removeEventListener("mousemove", onMouseMove);
        parent.removeEventListener("mouseleave", onMouseLeave);
      }
    };
  }

  /* ================= LANDING ================= */
  function renderLanding() {
    app.innerHTML = `
      <section class="hero view">
        <canvas class="hero-canvas" id="heroParticles"></canvas>
        <div class="badge">✨ AI-powered study tool</div>
        <h1>Turn your notes into flashcards <span class="grad">in seconds.</span></h1>
        <p class="sub">Study smarter by turning your notes into interactive flashcards automatically.</p>
        <div class="hero-actions">
          <button class="btn btn-primary btn-lg" onclick="location.hash='#/generator'">Create Flashcards</button>
          <button class="btn btn-lg" id="tryDemoBtn">Try a Demo</button>
        </div>
        <div class="demo-card-wrap">
          <div class="demo-card" id="demoCard" onclick="this.classList.toggle('flip')">
            <div class="inner">
              <div class="face"><div class="tag">Question</div><div class="q">What is the powerhouse of the cell?</div></div>
              <div class="face back"><div class="tag">Answer</div><div class="q">The mitochondria.</div></div>
            </div>
          </div>
        </div>
        <div class="demo-hint">tap the card to flip it</div>
      </section>
      <section class="features">
        <div class="feature"><div class="icon">🤖</div><h3>AI Flashcards</h3><p>Turn your notes into useful questions and answers automatically.</p></div>
        <div class="feature"><div class="icon">🎯</div><h3>Study Modes</h3><p>Review cards, test yourself, and track your progress as you go.</p></div>
        <div class="feature"><div class="icon">📈</div><h3>Track Progress</h3><p>See your accuracy, study streaks, and history in one place.</p></div>
      </section>`;
    $("#tryDemoBtn").onclick = tryDemo;
    initHeroParticles();
  }

  /* ================= GENERATOR ================= */
  const SUBJECTS = ["Mathematics", "Science", "Biology", "Chemistry", "Physics", "History", "Geography", "English", "Other"];
  const DIFFS = ["Easy", "Medium", "Hard", "Mixed"];
  const STYLES = [{ id: "q&a", label: "Question & Answer" }, { id: "term", label: "Term & Definition" }, { id: "mixed", label: "Mixed" }];

  const gen = { notes: "", subject: "Biology", difficulty: "Medium", number: 5, style: "q&a" };
  let genResults = [];

  function tryDemo() {
    gen.notes = "The mitochondria is the powerhouse of the cell. Photosynthesis converts sunlight into chemical energy. DNA stores genetic information. Enzymes speed up chemical reactions. The nucleus controls the cell and its activities.";
    gen.subject = "Biology"; gen.difficulty = "Medium"; gen.number = 5; gen.style = "q&a";
    navigate("#/generator");
    setTimeout(doGenerate, 350);
  }

  function renderGenerator() {
    app.innerHTML = `
      <div class="page-head"><h1>Paste in your study material</h1></div>
      <div class="view" style="max-width:760px;margin:0 auto">
        <div class="panel">
          <div class="field">
            <label>1. Paste in your study material <span class="hint">(enter content or upload a .txt / .pdf file)</span></label>
            <textarea id="genNotes" placeholder="Type or paste your study notes here...">${escapeHtml(gen.notes)}</textarea>
            <div class="char-count" id="genCount"></div>
            <div class="upload-box" id="genUpload">📄 Upload a file (.txt or .pdf)</div>
            <input type="file" id="genFile" accept=".txt,.pdf,text/plain,application/pdf" class="hidden" />
          </div>

          <div class="field">
            <label>2. Subject</label>
            <div class="select" id="genSubjectWrap">
              <button type="button" class="select-trigger" id="genSubjectBtn"><span id="genSubjectVal">${escapeHtml(gen.subject)}</span><span class="caret">▾</span></button>
              <div class="select-menu" id="genSubjectMenu"></div>
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>3. Difficulty</label>
              <div class="chips" id="genDiff">${DIFFS.map(d => `<button class="chip ${d === gen.difficulty ? "active" : ""}" data-d="${d}">${d}</button>`).join("")}</div>
            </div>
            <div class="field">
              <label>4. Card style</label>
              <div class="chips" id="genStyle">${STYLES.map(s => `<button class="chip ${s.id === gen.style ? "active" : ""}" data-s="${s.id}">${s.label}</button>`).join("")}</div>
            </div>
          </div>
          <div class="field">
            <label>5. Number of cards <span class="range-val" id="genNumVal">${gen.number}</span></label>
            <input type="range" id="genNum" min="1" max="50" step="1" value="${gen.number}" />
            <div class="range-scale"><span>1</span><span>25</span><span>50</span></div>
          </div>
          <div class="field-hint">💡 <b>Difficulty</b> shapes the cards the AI writes from <i>prose notes</i>. If you paste your own question/answer pairs, they’re used word-for-word, so difficulty doesn’t change them.</div>
          <button class="btn btn-primary btn-lg btn-block" id="genGo">✨ Generate Flashcards</button>
        </div>
        <div id="genOut"></div>
      </div>`;

    const notesEl = $("#genNotes");
    const uploadBox = $("#genUpload");
    const fileInput = $("#genFile");

    let uploadedFileName = "";

    const syncInputs = () => {
      gen.notes = notesEl.value;
      const count = gen.notes.length;
      $("#genCount").textContent = count.toLocaleString() + " characters";

      if (uploadedFileName) {
        uploadBox.classList.add("has-file");
        uploadBox.classList.remove("disabled");
        uploadBox.innerHTML = `📄 Loaded <b>${escapeHtml(uploadedFileName)}</b> (${count.toLocaleString()} chars) <button class="upload-clear-btn" id="genClearFile">Remove</button>`;
        notesEl.disabled = true;
        const clearBtn = $("#genClearFile");
        if (clearBtn) {
          clearBtn.onclick = (e) => {
            e.stopPropagation();
            uploadedFileName = "";
            fileInput.value = "";
            notesEl.disabled = false;
            notesEl.value = "";
            uploadBox.classList.remove("has-file", "disabled");
            uploadBox.innerHTML = "📄 Upload a file (.txt or .pdf)";
            syncInputs();
          };
        }
      } else if (notesEl.value.trim().length > 0) {
        uploadBox.classList.add("disabled");
        uploadBox.classList.remove("has-file");
        uploadBox.innerHTML = "📄 File upload disabled (manual notes entered above)";
        notesEl.disabled = false;
      } else {
        uploadBox.classList.remove("disabled", "has-file");
        uploadBox.innerHTML = "📄 Upload a file (.txt or .pdf)";
        notesEl.disabled = false;
      }
    };

    notesEl.addEventListener("input", syncInputs);
    syncInputs();

    uploadBox.onclick = () => {
      if (uploadBox.classList.contains("disabled") || uploadedFileName) return;
      fileInput.click();
    };

    fileInput.addEventListener("change", async e => {
      const f = e.target.files[0];
      if (!f) return;
      // PDFs are parsed server-side (pypdf); plain text is read in the browser.
      if (/\.pdf$/i.test(f.name)) {
        const fd = new FormData();
        fd.append("file", f);
        try {
          const res = await fetch("/api/upload", { method: "POST", body: fd });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) { toast(data.error || "Couldn't read that PDF.", "error"); fileInput.value = ""; return; }
          const txt = data.text || "";
          uploadedFileName = f.name;
          notesEl.value = txt.slice(0, 12000);
          syncInputs();
          toast("PDF loaded 📄 (" + txt.length.toLocaleString() + " chars)");
        } catch (err) {
          toast("Couldn't read that PDF.", "error");
          fileInput.value = "";
        }
        return;
      }
      const r = new FileReader();
      r.onload = () => {
        let txt = String(r.result).replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
        uploadedFileName = f.name;
        notesEl.value = txt.slice(0, 12000);
        syncInputs();
        toast("File loaded 📄 (" + txt.length.toLocaleString() + " chars)");
      };
      r.readAsText(f);
    });

    customSelect("#genSubjectBtn", "#genSubjectVal", "#genSubjectMenu",
      SUBJECTS.map(s => ({ v: s, label: s })),
      () => gen.subject,
      v => { gen.subject = v; });
    chipBind("#genDiff", "data-d", v => gen.difficulty = v);
    chipBind("#genStyle", "data-s", v => gen.style = v);
    const range = $("#genNum");
    range.addEventListener("input", e => { gen.number = +e.target.value; $("#genNumVal").textContent = gen.number; });
    $("#genGo").onclick = doGenerate;
  }
  function chipBind(sel, attr, apply) {
    $$(sel + " .chip").forEach(c => c.onclick = () => {
      $$(sel + " .chip").forEach(x => x.classList.toggle("active", x === c));
      apply(c.getAttribute(attr));
    });
  }

  /* Custom styled dropdown (replaces native <select> so the open list is
     styled with rounded corners instead of the OS default hard-edged menu). */
  function closeSelects() {
    $$(".select.open").forEach(m => m.classList.remove("open"));
  }
  function customSelect(btnId, valId, menuId, options, getVal, onChange) {
    // options: [{ v, label }]
    const btn = $(btnId), wrap = btn.closest(".select"), menu = $(menuId), valEl = $(valId);
    function paint() {
      menu.innerHTML = options.map(o =>
        `<button type="button" class="select-opt ${o.v === getVal() ? "active" : ""}" data-v="${escapeHtml(o.v)}">${escapeHtml(o.label)}</button>`
      ).join("");
      const cur = options.find(o => o.v === getVal());
      valEl.textContent = cur ? cur.label : getVal();
      $$(".select-opt", menu).forEach(b => {
        b.addEventListener("click", () => {
          onChange(b.getAttribute("data-v"));
          closeSelects();
          paint();
        });
      });
    }
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const isOpen = wrap.classList.contains("open");
      closeSelects();
      if (!isOpen) wrap.classList.add("open");
    });
    paint();
  }

  async function doGenerate() {
    if (!gen.notes.trim()) { toast("Paste your notes first", "error"); return; }
    const out = $("#genOut"); if (!out) return;
    out.innerHTML = loaderHtml("Turning your notes into flashcards…");
    const { ok, status, data } = await api("/generate", {
      method: "POST",
      body: { notes: gen.notes, subject: gen.subject, difficulty: gen.difficulty, number: gen.number, style: gen.style },
    });
    if (!ok) {
      if (status === 402 && data.error === "sign_in_required") { renderFreeLocked(); return; }
      out.innerHTML = `<div class="empty"><div class="em">😕</div><h3>Couldn't generate</h3><p>${escapeHtml(data.error || "Please try again.")}</p></div>`;
      return;
    }
    genResults = data.cards || [];
    if (!genResults.length) {
      out.innerHTML = `<div class="empty"><div class="em">🤔</div><h3>No flashcards found</h3><p>Memora builds cards from the <b>facts and definitions</b> in your notes. Try pasting real study material (terms, definitions, Q&amp;A, tables) instead of a request like “make me a deck”.</p></div>`;
      return;
    }
    if (data.limited) {
      renderResultsPreview(genResults, { limited: true });
      openAuth("Your first flashcard is ready! 🎉",
        "Sign in to create more flashcards and save your study decks.",
        doGenerate);
    } else {
      renderResultsPreview(genResults, { limited: false });
    }
  }

  function renderFreeLocked() {
    app.innerHTML = `
      <div class="empty view">
        <div class="em">🔒</div>
        <h3>You've used your free flashcard</h3>
        <p>Sign in to generate as many flashcards as you like and save your study decks.</p>
        <button class="btn btn-primary btn-lg" onclick="App.openAuth()">Sign In or Create Account</button>
      </div>`;
  }

  function renderResultsPreview(cards, opts) {
    const out = $("#genOut"); if (!out) return;
    let html = `<div class="panel" style="margin-top:22px">
      <div class="section-title" style="margin-top:0">Your flashcards</div>
      <div class="section-sub">${cards.length} card${cards.length > 1 ? "s" : ""} · review below, then save to a deck.</div>`;
    if (opts && opts.limited) {
      html += `<div class="free-note" style="display:flex;align-items:flex-start">🎉 <span>This is your <b>one free flashcard</b>. Create an account (it takes seconds) to unlock the full set of <b>${gen.number}</b> cards and save them.</span></div>`;
    }
    html += `<div class="stack">`;
    cards.forEach((c, i) => {
      html += `<div class="fcard">
        <div class="f-head"><span class="num">#${i + 1}</span><span style="font-style:italic">${escapeHtml(c.style || "")}</span></div>
        <div class="f-body">
          <div class="f-side"><div class="lbl">Question</div><div class="txt">${escapeHtml(c.front)}</div></div>
          <div class="divider"></div>
          <div class="f-side"><div class="lbl">Answer</div><div class="txt">${escapeHtml(c.back)}</div></div>
        </div>
      </div>`;
    });
    html += `</div>`;
    if (state.user) {
      html += `<div style="display:flex;gap:12px;margin-top:18px;flex-wrap:wrap">
        <input type="text" id="deckName" placeholder="Deck name (e.g. Biology — Cells)" style="flex:1;min-width:220px" />
        <button class="btn btn-primary" id="saveDeckBtn">💾 Save Deck</button>
        <button class="btn" id="genAgainBtn">↻ Regenerate</button>
      </div>`;
    } else {
      html += `<button class="btn btn-primary btn-block btn-lg" style="margin-top:18px" onclick="App.openAuth('Sign in to save this deck','Keep your decks forever with a free account.')">Save this deck — Sign In</button>`;
    }
    html += `</div>`;
    out.innerHTML = html;
    if (state.user) {
      $("#saveDeckBtn").onclick = saveDeck;
      $("#genAgainBtn").onclick = doGenerate;
    }
  }

  async function saveDeck() {
    const name = ($("#deckName").value.trim() || (gen.subject === "Other" ? "My study deck" : gen.subject + " deck"));
    const { ok, status, data } = await api("/decks", { method: "POST", body: { name, subject: gen.subject, cards: genResults } });
    if (!ok) {
      if (status === 403 && data.error === "deck_limit") return toast(data.message || "Deck limit reached.", "error");
      return toast("Couldn't save deck", "error");
    }
    toast("Deck saved to your library ✅", "success");
    navigate("#/deck/" + data.deck.id);
  }

  /* ================= DASHBOARD ================= */
  const SUBJ_EMOJI = {"math": "➗", "science": "🔬", "bio": "🧬", "chem": "⚗️", "phys": "⚡", "english": "📖", "history": "🏛️", "geo": "🌍", "tech": "💻", "computer": "💻", "art": "🎨", "music": "🎵", "other": "📚"};
  function deckEmoji(subject) {
    const s = (subject || "").toLowerCase();
    for (const k in SUBJ_EMOJI) if (s.includes(k)) return SUBJ_EMOJI[k];
    return "📚";
  }
  const moodFaces = ["🧪", "🧠", "🚀", "😎", "⭐", "⚡"];
  const moodLines = [
    "Ready to make today count? 💪",
    "Little steps every day = big results 🚀",
    "You've got this — one card at a time ⭐",
    "Future-you will thank today-you 📚",
    "Smart students study smart 😎",
    "Let's make learning fun! ⚡",
  ];
  let moodIdx = 0;
  function cycleMood() {
    const el = $("#dashMood"); if (!el) return;
    moodIdx = (moodIdx + 1) % moodFaces.length;
    el.textContent = moodFaces[moodIdx];
    el.classList.add("pop");
    const m = $("#dashMsg"); if (m) m.textContent = moodLines[moodIdx];
    setTimeout(() => el.classList.remove("pop"), 350);
  }
  function deckWeakCount(d) { return (d.card_count || 0) - (d.mastered_count || 0); }

  async function renderDashboard() {
    const { data } = await api("/decks");
    const decks = data.decks || [];
    const st = (await api("/stats")).data || {};
    const favs = decks.filter(d => d.favorite);
    const recent = [...decks].sort((a, b) => (b.last_studied || b.updated_at) - (a.last_studied || a.updated_at)).slice(0, 4);
    const show = (favs.length ? [...favs, ...recent.filter(r => !favs.includes(r))] : recent).slice(0, 6);
    const weakTotal = decks.reduce((a, d) => a + deckWeakCount(d), 0);
    const firstName = (state.user && state.user.name ? state.user.name.split(" ")[0] : "friend");
    app.innerHTML = `
      <div class="page-head"><h1>Dashboard</h1><div class="spacer"></div>
        <button class="btn btn-primary" onclick="location.hash='#/generator'">+ Create New Deck</button></div>
      <div class="dash-hero">
        <button class="dash-mood" id="dashMood" onclick="App.cycleMood()" title="Tap to change your mood">🎉</button>
        <div class="dash-text">
          <div class="dash-greet">Hey ${escapeHtml(firstName)}! 👋</div>
          <div class="dash-sub" id="dashMsg">${moodLines[0]}</div>
        </div>
        <div class="spacer"></div>
        ${decks.length ? `<button class="btn btn-primary btn-lg" onclick="App.smartReviewAll()">🧠 Smart Review</button>` : ""}
      </div>
      <div class="stats-row">
        <button class="stat link" onclick="location.hash='#/library'"><div class="label">Total cards</div><div class="value">${st.total_cards || 0}</div><div class="sub">across all your decks</div></button>
        <button class="stat link" onclick="location.hash='#/stats'"><div class="label">Cards reviewed</div><div class="value">${st.cards_reviewed || 0}</div><div class="sub">since you started</div></button>
        <button class="stat link" onclick="location.hash='#/stats'"><div class="label">Study streak</div><div class="value">🔥 ${st.study_streak || 0}</div><div class="sub">consecutive days</div></button>
        <button class="stat link" onclick="location.hash='#/review'"><div class="label">To review</div><div class="value">🎯 ${weakTotal}</div><div class="sub">weak cards by deck</div></button>
      </div>
      ${decks.length ? deckGridHtml(show, "Your study corner", true) : emptyState()}`;
  }
  function emptyState() {
    return `<div class="empty"><div class="em">📚</div><h3>No decks yet</h3>
      <p>Turn your notes into your first set of flashcards. It only takes a few seconds.</p>
      <button class="btn btn-primary btn-lg" onclick="location.hash='#/generator'">Create Flashcards</button></div>`;
  }
  function deckGridHtml(decks, title) {
    return `<div class="section-title">${title || "Your decks"}</div><div class="section-sub">Tap a deck to open it</div>
      <div class="grid-decks">${decks.map(deckCardHtml).join("")}</div>`;
  }
  function deckCardHtml(d) {
    const weak = deckWeakCount(d);
    return `
      <div class="deck" onclick="location.hash='#/deck/${d.id}'">
        <button class="fav-star ${d.favorite ? "on" : ""}" onclick="event.stopPropagation();App.toggleFav(${d.id}, ${d.favorite ? "0" : "1"})">${d.favorite ? "★" : "☆"}</button>
        <div class="deck-emoji">${deckEmoji(d.subject)}</div>
        <div class="deck-subject">${escapeHtml(d.subject)}</div>
        <h3>${escapeHtml(d.name)}</h3>
        <div class="meta">${d.card_count || 0} cards${d.accuracy != null ? " · " + Math.round(d.accuracy) + "% acc" : ""}${weak ? " · " + weak + " to review" : ""}</div>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="btn" style="flex:1;padding:8px" onclick="event.stopPropagation();location.hash='#/study/${d.id}'">▶ Study</button>
          ${d.favorite ? `<button class="btn btn-danger" disabled title="Unfavorite before deleting" style="opacity:.4;cursor:not-allowed;padding:8px">🗑</button>` : `<button class="btn btn-danger" style="padding:8px" onclick="event.stopPropagation();App.deleteDeckConfirm(${d.id})">🗑</button>`}
        </div>
      </div>`;
  }
  async function toggleFav(id, on) {
    await api("/decks/" + id, { method: "PATCH", body: { favorite: !!on } });
    route();
  }

  /* ================= REVIEW (weak cards, by deck) ================= */
  async function renderReview() {
    const { data } = await api("/decks");
    const decks = data.decks || [];
    const rows = [];
    let totalWeak = 0;
    for (const d of decks) {
      const weak = (d.card_count || 0) - (d.mastered_count || 0);
      if (weak > 0) { rows.push({ deck: d, weak }); totalWeak += weak; }
    }
    if (!rows.length) {
      app.innerHTML = `<div class="empty view"><div class="em">🎉</div><h3>All caught up!</h3><p>No weak cards to review right now. Great studying!</p><button class="btn btn-primary btn-lg" onclick="location.hash='#/dashboard'">Back to Dashboard</button></div>`;
      return;
    }
    app.innerHTML = `
      <div class="page-head"><h1>Review</h1><div class="spacer"></div>
        <button class="btn btn-primary btn-lg" onclick="App.smartReviewAll()">🧠 Review All Decks</button></div>
      <div class="view">
        <p class="section-sub" style="margin-bottom:20px">${totalWeak} weak card${totalWeak > 1 ? "s" : ""} across ${rows.length} deck${rows.length > 1 ? "s" : ""}. Pick a deck to review first — its weak cards are shuffled.</p>
        <div class="section-title" style="margin-top:0">Choose a deck</div>
        <div class="grid-decks">${rows.map(r => reviewDeckCard(r.deck, r.weak)).join("")}</div>
      </div>`;
  }
  function reviewDeckCard(d, weak) {
    return `
      <div class="deck">
        <div class="deck-emoji">${deckEmoji(d.subject)}</div>
        <div class="deck-subject">${escapeHtml(d.subject)}</div>
        <h3>${escapeHtml(d.name)}</h3>
        <div class="meta">${weak} weak card${weak > 1 ? "s" : ""} to review · ${d.card_count || 0} total</div>
        <div style="display:flex;gap:8px;margin-top:14px">
          <button class="btn btn-primary" onclick="App.practiceWeak(${d.id})">▶ Review ${weak}</button>
        </div>
      </div>`;
  }

  /* ================= LIBRARY ================= */
  let libSort = "newest", libQuery = "";
  async function renderLibrary() {
    const { data } = await api("/decks");
    let decks = data.decks || [];
    if (libQuery) decks = decks.filter(d => d.name.toLowerCase().includes(libQuery.toLowerCase()));
    decks = sortDecks(decks, libSort);
    app.innerHTML = `
      <div class="page-head"><h1>My Decks</h1><div class="spacer"></div>
        <button class="btn" onclick="App.openImport()">📥 Import</button>
        <button class="btn btn-primary" onclick="location.hash='#/generator'">+ New Deck</button></div>
      <div class="toolbar">
        <div class="search"><span class="icon">🔍</span><input id="libSearch" placeholder="Search decks…" value="${escapeHtml(libQuery)}" /></div>
        <div class="select" id="libSortWrap">
          <button type="button" class="select-trigger" id="libSortBtn"><span id="libSortVal"></span><span class="caret">▾</span></button>
          <div class="select-menu" id="libSortMenu"></div>
        </div>
      </div>
      ${decks.length === 0
        ? (libQuery ? `<div class="empty"><h3>No matches</h3><p>Try a different search.</p></div>` : emptyState())
        : `<div class="grid-decks">${decks.map(libraryCard).join("")}</div>`}`;
    $("#libSearch").addEventListener("input", e => { libQuery = e.target.value; renderLibrary(); });
    customSelect("#libSortBtn", "#libSortVal", "#libSortMenu",
      [{ v: "newest", label: "Newest" }, { v: "oldest", label: "Oldest" }, { v: "studied", label: "Most studied" }],
      () => libSort,
      v => { libSort = v; renderLibrary(); });
  }
  function sortDecks(decks, sort) {
    const arr = [...decks];
    if (sort === "newest") return arr.sort((a, b) => b.created_at - a.created_at);
    if (sort === "oldest") return arr.sort((a, b) => a.created_at - b.created_at);
    return arr.sort((a, b) => (b.times_studied || 0) - (a.times_studied || 0));
  }
  function libraryCard(d) {
    const weak = deckWeakCount(d);
    return `
      <div class="deck">
        <button class="fav-star ${d.favorite ? "on" : ""}" onclick="App.toggleFav(${d.id}, ${d.favorite ? "0" : "1"})">${d.favorite ? "★" : "☆"}</button>
        <div class="deck-emoji">${deckEmoji(d.subject)}</div>
        <div class="deck-subject">${escapeHtml(d.subject)}</div>
        <h3 style="cursor:pointer" onclick="location.hash='#/deck/${d.id}'">${escapeHtml(d.name)}</h3>
        <div class="meta">${d.card_count || 0} cards${d.accuracy != null ? " · " + Math.round(d.accuracy) + "% acc" : ""}${weak ? " · " + weak + " to review" : ""}</div>
        <div style="display:flex;gap:8px;margin-top:14px">
          <button class="btn btn-primary" onclick="location.hash='#/deck/${d.id}'">Open</button>
          <button class="btn" onclick="location.hash='#/study/${d.id}'">Study</button>
          <button class="btn" onclick="App.quizDeck(${d.id})">Quiz</button>
          ${d.favorite ? `<button class="btn btn-danger" disabled title="Unfavorite before deleting" style="opacity:.4;cursor:not-allowed">🗑</button>` : `<button class="btn btn-danger" onclick="App.deleteDeckConfirm(${d.id})">🗑</button>`}
        </div>
      </div>`;
  }
  function deleteDeckConfirm(id) {
    // Favourited decks are protected by the server (409); the UI also disables
    // the delete button for them. No async prefetch needed here — the modal
    // opens instantly and the server enforces the rule.
    askConfirm("Delete deck?", "This permanently deletes the deck and its flashcards.", "Delete", async () => {
      const r = await api("/decks/" + id, { method: "DELETE" });
      if (!r.ok) {
        toast(r.data.message || r.data.error || "Couldn't delete this deck.", "error");
        return;
      }
      toast("Deck deleted", "success");
      if (location.hash.startsWith("#/deck/")) navigate("#/library"); else route();
    });
  }

  /* ================= DECK DETAIL ================= */
  async function downloadDeck(deckId, format) {
    try {
      const headers = {};
      if (state.token) headers["Authorization"] = "Bearer " + state.token;
      else headers["X-Guest-Id"] = state.guestId;
      const res = await fetch(`/api/decks/${deckId}/export?format=${format}`, { headers });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        toast(d.error || "Couldn't download the deck.", "error");
        return;
      }
      const blob = await res.blob();
      const ext = format === "pdf" ? "pdf" : format === "json" ? "json" : "txt";
      const a = document.createElement("a");
      const url = URL.createObjectURL(blob);
      a.href = url;
      a.download = "deck-" + deckId + "." + ext;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast("Downloaded your deck as " + format.toUpperCase() + " ✅");
    } catch (err) {
      toast("Couldn't download the deck.", "error");
    }
  }

  async function renderDeck(id) {
    const { ok, data } = await api("/decks/" + id);
    if (!ok || !data.deck) { app.innerHTML = `<div class="empty view"><h3>Deck not found</h3></div>`; return; }
    const d = data.deck, cards = d.cards || [];
    const weakCount = cards.filter(c => !c.mastered).length;
    // AI feedback about the last study round
    const fb = d.last_feedback;
    let feedbackHtml = "";
    if (fb && fb.reviewed) {
      if (fb.missed && fb.missed.length) {
        const numById = {};
        cards.forEach((c, i) => numById[c.id] = i + 1);
        const wrongNums = (fb.missed || []).map(m => numById[m.id]).filter(Boolean).sort((a, b) => a - b);
        const nums = wrongNums.length ? wrongNums.join(", ") : "—";
        feedbackHtml = `<div class="feedback"><div class="fb-emoji">🧠</div><div class="fb-body">
          <div class="fb-title">Last round: ${fb.correct}/${fb.reviewed} correct · ${fb.accuracy}%</div>
          <div class="fb-sub">You missed ${fb.missed.length} question${fb.missed.length > 1 ? "s" : ""} — question <b>${nums}</b>. Tap <b>Smart Review</b> to reinforce them. 💪</div></div></div>`;
      } else {
        feedbackHtml = `<div class="feedback ok"><div class="fb-emoji">🏆</div><div class="fb-body">
          <div class="fb-title">Last round: perfect ${fb.accuracy}% 🎉</div>
          <div class="fb-sub">You got every card right. Keep that streak alive!</div></div></div>`;
      }
    }
    app.innerHTML = `
      <div class="page-head"><a class="breadcrumb" href="#/library">← My Decks</a><div class="spacer"></div></div>
      <div class="view">
        ${feedbackHtml}
        <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
          <div class="deck-emoji big">${deckEmoji(d.subject)}</div>
          <div>
            <h1 style="margin:0">${escapeHtml(d.name)}</h1>
            <div class="deck-subject">${escapeHtml(d.subject)}</div>
          </div>
          <div class="spacer"></div>
          <button class="btn btn-primary btn-lg" onclick="location.hash='#/study/${d.id}'">▶ Start Study</button>
          <button class="btn btn-lg" onclick="App.quizDeck(${d.id})">📝 Quiz</button>
          <button class="btn btn-lg" onclick="App.smartReview(${d.id})">🧠 Smart Review</button>
        </div>
        <div class="meta muted" style="margin:8px 0 18px">${cards.length} cards${d.accuracy != null ? " · " + Math.round(d.accuracy) + "% accuracy" : ""}${weakCount ? " · " + weakCount + " to review" : ""}</div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 18px">
          <span class="muted" style="font-size:13px;font-weight:600">⬇ Download:</span>
          <button class="btn" onclick="App.downloadDeck(${d.id},'pdf')">📄 PDF</button>
          <button class="btn" onclick="App.downloadDeck(${d.id},'txt')">📝 TXT</button>
        </div>
        <div class="panel" style="margin-bottom:18px">
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
            <input type="text" id="deckRename" value="${escapeHtml(d.name)}" style="flex:1;min-width:200px" />
            <button class="btn" onclick="App.renameDeck(${d.id})">Rename</button>
            <button class="btn" onclick="App.toggleFav(${d.id}, ${d.favorite ? "0" : "1"})">${d.favorite ? "Unfavorite ☆" : "Favorite ★"}</button>
            ${d.favorite ? `<button class="btn btn-danger" disabled title="Unfavorite before deleting" style="opacity:.4;cursor:not-allowed">Delete deck</button>` : `<button class="btn btn-danger" onclick="App.deleteDeckConfirm(${d.id})">Delete deck</button>`}
          </div>
        </div>
        <div class="panel">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div class="section-title" style="margin:0">Cards</div>
            <button class="btn" onclick="App.addCardForm(${d.id})">+ Add card</button>
          </div>
          <div id="addCardArea"></div>
          <div class="stack" style="margin-top:16px">
            ${cards.length ? cards.map((c, i) => flashcardHtml(d.id, c, i)).join("") : `<div class="empty"><h3>No cards yet</h3><p>Add a card below or generate one from the Create page.</p></div>`}
          </div>
        </div>
      </div>`;
  }
  function flashcardHtml(deckId, c, i) {
    return `
      <div class="fcard" data-cid="${c.id}">
        <div class="f-head"><span class="num">#${i + 1}</span><span style="font-style:italic">${escapeHtml(c.style || "")}</span>
          <div class="f-actions">
            <button onclick="App.editCard(${deckId}, ${c.id})" title="Edit">✏️</button>
            <button onclick="App.regenCard(${deckId}, ${c.id})" title="Regenerate">↻</button>
            <button onclick="App.delCard(${deckId}, ${c.id})" title="Delete">🗑</button>
          </div>
        </div>
        <div class="f-body">
          <div class="f-side"><div class="lbl">Front</div><div class="txt">${escapeHtml(c.front)}</div></div>
          <div class="divider"></div>
          <div class="f-side"><div class="lbl">Back</div><div class="txt">${escapeHtml(c.back)}</div></div>
        </div>
      </div>`;
  }
  async function renameDeck(id) {
    const name = $("#deckRename").value.trim();
    if (!name) return;
    await api("/decks/" + id, { method: "PATCH", body: { name } });
    toast("Deck renamed ✅");
    renderDeck(id);
  }
  function addCardForm(deckId) {
    $("#addCardArea").innerHTML = `
      <div class="panel" style="margin-top:14px;box-shadow:none">
        <div class="field-row">
          <div class="field"><label>Front</label><input type="text" id="ncFront" placeholder="Question" /></div>
          <div class="field"><label>Back</label><input type="text" id="ncBack" placeholder="Answer" /></div>
        </div>
        <div style="display:flex;gap:10px">
          <button class="btn btn-primary" onclick="App.saveNewCard(${deckId})">Add card</button>
          <button class="btn btn-ghost" onclick="$('#addCardArea').innerHTML=''">Cancel</button>
        </div>
      </div>`;
  }
  async function saveNewCard(deckId) {
    const front = $("#ncFront").value.trim(), back = $("#ncBack").value.trim();
    if (!front || !back) { toast("Fill in both sides", "error"); return; }
    await api("/decks/" + deckId + "/cards", { method: "POST", body: { front, back } });
    toast("Card added ✅");
    renderDeck(deckId);
  }
  function editCard(deckId, cardId) {
    const el = $(`.fcard[data-cid="${cardId}"]`); if (!el) return;
    const f = el.querySelectorAll(".txt");
    el.innerHTML = `
      <div class="f-body" style="padding:18px">
        <div class="f-side"><div class="lbl">Front</div><textarea id="efF" style="min-height:70px">${escapeHtml(f[0].textContent)}</textarea></div>
        <div class="divider"></div>
        <div class="f-side"><div class="lbl">Back</div><textarea id="efB" style="min-height:70px">${escapeHtml(f[1].textContent)}</textarea></div>
      </div>
      <div style="display:flex;gap:10px;padding:0 18px 16px">
        <button class="btn btn-primary" onclick="App.saveEditCard(${deckId}, ${cardId})">Save</button>
        <button class="btn btn-ghost" onclick="App.renderDeckNow(${deckId})">Cancel</button>
      </div>`;
  }
  async function saveEditCard(deckId, cardId) {
    const front = $("#efF").value.trim(), back = $("#efB").value.trim();
    if (!front || !back) { toast("Both sides required", "error"); return; }
    await api("/cards/" + cardId, { method: "PATCH", body: { front, back } });
    toast("Card updated ✅");
    renderDeck(deckId);
  }
  async function delCard(deckId, cardId) {
    await api("/cards/" + cardId, { method: "DELETE" });
    toast("Card deleted");
    renderDeck(deckId);
  }
  async function regenCard(deckId, cardId) {
    const { data } = await api("/decks/" + deckId);
    const deck = data.deck;
    // Rebuild the notes context from the whole deck (name + every card's
    // front/back), so regeneration isn't based on the deck name alone.
    const notes = deck.cards
      .map(c => c.front + (c.front.trim().endsWith("?") ? " " : ". ") + c.back)
      .join(" ");
    const context = (deck.name ? deck.name + ". " : "") + notes;
    toast("Regenerating card…");
    const { ok, data: g } = await api("/generate", { method: "POST", body: { notes: context, subject: deck.subject, number: 1 } });
    if (ok && g.cards && g.cards[0]) {
      const c = g.cards[0];
      await api("/cards/" + cardId, { method: "PATCH", body: { front: c.front, back: c.back } });
      toast("Card regenerated ✅");
    }
    renderDeck(deckId);
  }

  /* ================= STUDY ================= */
  let studyShuffle = true;   // shuffle deck order when studying
  let studySource = [];      // the deck's original card order
  async function renderStudy(deckId) {
    const { ok, data } = await api("/decks/" + deckId);
    if (!ok || !data.deck || !data.deck.cards.length) {
      app.innerHTML = `<div class="empty view"><div class="em">📭</div><h3>Nothing to study</h3><p>This deck has no cards yet.</p><button class="btn btn-primary" onclick="location.hash='#/generator'">Create cards</button></div>`;
      return;
    }
    mountStudy(deckId, [...data.deck.cards], data.deck.name, false);
  }

  // Reliably leave a study/review session even when the target hash equals the
  // current one (which would otherwise fire no hashchange and leave the user stuck).
  function leaveStudy(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  // Start a study session on a specific set of cards (full deck or a practice subset).
  function mountStudy(deckId, cards, name, isPractice, studyUrl) {
    if (cleanupStudyMode) {
      cleanupStudyMode();
      cleanupStudyMode = null;
    }

    studySource = cards;
    const ordered = studyShuffle ? shuffle([...cards]) : [...cards];

    app.innerHTML = `
      <div class="page-head">
        <a class="breadcrumb" href="${deckId ? '#/deck/' + deckId : '#/library'}" onclick="App.leaveStudy('${deckId ? '#/deck/' + deckId : '#/library'}');return false;">← ${deckId ? "Back to Deck" : "My Decks"}</a>
        <div class="spacer"></div>
        <button class="btn btn-sm" id="sShuffle" title="Toggle shuffle">🔀 ${studyShuffle ? "Shuffled" : "In order"}</button>
        <div class="muted" style="font-size:13.5px;font-weight:600" id="sCounter">Card 1 of ${ordered.length}</div>
      </div>
      <div class="study-area view">
        <div class="study-progress" id="sProg"></div>
        <div class="study-flip" id="sFlip" tabindex="0" role="button" title="Click or press Space to flip">
          <div class="inner">
            <div class="s-face"><div class="hint">Question</div><div class="q" id="sQ"></div></div>
            <div class="s-face back2"><div class="hint">Answer</div><div class="q" id="sA"></div></div>
          </div>
        </div>
        <div class="tap-hint">Tap card or press <kbd class="k-hint">Space</kbd> to flip</div>
        <div class="verdicts hidden" id="sVerdicts">
          <button class="verdict didnt" data-r="0" title="Shortcut: 1"><span class="em">❌</span>Didn't Know <kbd class="k-hint">1</kbd></button>
          <button class="verdict almost" data-r="0" title="Shortcut: 2"><span class="em">😐</span>Almost <kbd class="k-hint">2</kbd></button>
          <button class="verdict knew" data-r="1" title="Shortcut: 3"><span class="em">✅</span>Knew It <kbd class="k-hint">3</kbd></button>
        </div>
        <div style="display:flex;gap:18px;margin-top:20px;color:var(--text-faint);font-size:12.5px;align-items:center;flex-wrap:wrap;justify-content:center">
          <span><kbd class="k-hint">←</kbd> Previous</span>
          <span><kbd class="k-hint">Space</kbd> Flip</span>
          <span><kbd class="k-hint">1</kbd> <kbd class="k-hint">2</kbd> <kbd class="k-hint">3</kbd> Grade</span>
          <span><kbd class="k-hint">→</kbd> Flip / Next</span>
        </div>
      </div>`;
    const sh = $("#sShuffle");
    if (sh) sh.onclick = () => { studyShuffle = !studyShuffle; mountStudy(deckId, studySource, name, isPractice, studyUrl); };
    runStudy(ordered, name, deckId, isPractice, studyUrl);
  }

  // Smart Review: mix your weakest cards first with a few known ones for spaced reinforcement.
  async function smartReview(deckId) {
    const { ok, data } = await api("/decks/" + deckId);
    if (!ok || !data.deck || !data.deck.cards.length) return;
    const cards = data.deck.cards;
    const weak = cards.filter(c => !c.mastered).sort((a, b) => (a.times_correct || 0) - (b.times_correct || 0));
    const strong = shuffle(cards.filter(c => c.mastered));
    const pick = Math.min(strong.length, Math.ceil(cards.length * 0.3));
    const set = [...weak, ...strong.slice(0, pick)];
    mountStudy(deckId, set.length ? shuffle(set) : cards, data.deck.name + " · smart review", true, "/decks/" + deckId + "/study");
  }

  // Smart Review across all decks: weak cards from everywhere, plus some known ones.
  async function smartReviewAll() {
    const { data } = await api("/decks");
    const decks = data.decks || [];
    if (!decks.length) { toast("Create a deck first, then smart review! 📚"); return; }
    let collected = [];
    for (const d of decks) {
      const r = await api("/decks/" + d.id);
      const cards = (r.data.deck && r.data.deck.cards) || [];
      const weak = shuffle(cards.filter(c => !c.mastered).sort((a, b) => (a.times_correct || 0) - (b.times_correct || 0)));
      const strong = shuffle(cards.filter(c => c.mastered));
      collected.push(...weak, ...strong.slice(0, Math.ceil(weak.length * 0.5)));
    }
    if (!collected.length) { toast("Nothing to review — you're all caught up! 🎉"); return; }
    mountStudy(null, shuffle(collected), "Smart review across decks", true, "/smart/review");
  }

  // Personalized practice: study only the cards the user hasn't mastered yet.
  async function practiceWeak(deckId) {
    const { ok, data } = await api("/decks/" + deckId);
    if (!ok || !data.deck) return;
    const weak = data.deck.cards.filter(c => !c.mastered);
    if (!weak.length) { toast("No weak cards right now — nice work! 🎉"); return; }
    mountStudy(deckId, shuffle([...weak]), data.deck.name + " · weak cards", true);
  }

  // Personalized practice: re-study exactly the cards missed in the last session.
  function practiceMissed(deckId) {
    const last = lastMissed && lastMissed.deckId === deckId ? lastMissed : null;
    if (!last || !last.cards.length) { toast("No missed cards to practice right now."); return; }
    mountStudy(deckId, shuffle([...last.cards]), last.name + " · missed cards", true);
  }

  let lastMissed = null;
  function shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
  
  function runStudy(cards, deckName, deckId, isPractice, studyUrl) {
    let i = 0, correct = 0;
    const results = [];
    const grades = [];
    const start = Date.now();
    let isGrading = false;

    const prog = $("#sProg"), flip = $("#sFlip"), verdicts = $("#sVerdicts");
    const sQ = $("#sQ"), sA = $("#sA"), sCounter = $("#sCounter");

    function paintProg() {
      if (!prog) return;
      prog.innerHTML = cards.map((c, idx) => {
        if (idx < i) {
          const g = grades[idx] || "wrong";
          return `<i class="${g === "correct" ? "correct" : g}"></i>`;
        }
        return `<i class="${idx === i ? "done" : ""}"></i>`;
      }).join("");
      if (sCounter) {
        sCounter.textContent = `Card ${Math.min(i + 1, cards.length)} of ${cards.length}`;
      }
    }

    function showCard() {
      if (!sQ || !sA || !flip || !verdicts) return;
      sQ.textContent = cards[i].front;
      sA.textContent = cards[i].back;
      flip.classList.remove("flipped");
      verdicts.classList.remove("hidden");
      verdicts.querySelectorAll(".verdict").forEach(x => x.disabled = false);
      isGrading = false;
      paintProg();
    }

    flip.onclick = () => flip.classList.toggle("flipped");

    function applyVerdict(isCorrect, grade) {
      if (isGrading || i >= cards.length) return;
      isGrading = true;

      grades[i] = grade || (isCorrect ? "correct" : "wrong");
      results[i] = isCorrect;
      correct = results.filter(Boolean).length;
      verdicts.querySelectorAll(".verdict").forEach(x => x.disabled = true);

      i++;
      if (i >= cards.length) {
        finish();
        return;
      }
      setTimeout(() => {
        showCard();
      }, 240);
    }

    const verdictBtns = $$(".verdict", verdicts);
    if (verdictBtns[0]) verdictBtns[0].onclick = () => applyVerdict(false, "wrong");
    if (verdictBtns[1]) verdictBtns[1].onclick = () => applyVerdict(false, "almost");
    if (verdictBtns[2]) verdictBtns[2].onclick = () => applyVerdict(true, "correct");

    /* ---------- keyboard shortcuts ---------- */
    function onKeyDown(e) {
      const tag = e.target && e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!$("#authModal").classList.contains("hidden") || !$("#confirmModal").classList.contains("hidden")) return;

      if (e.code === "Space" || e.key === " ") {
        e.preventDefault();
        flip.classList.toggle("flipped");
      } else if (e.key === "1") {
        e.preventDefault();
        applyVerdict(false, "wrong");
      } else if (e.key === "2") {
        e.preventDefault();
        applyVerdict(false, "almost");
      } else if (e.key === "3") {
        e.preventDefault();
        applyVerdict(true, "correct");
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        if (i > 0) {
          i--;
          grades.splice(i, 1);
          results.splice(i, 1);
          correct = results.filter(Boolean).length;
          showCard();
        }
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        if (!flip.classList.contains("flipped")) {
          flip.classList.add("flipped");
        }
      }
    }

    window.addEventListener("keydown", onKeyDown);

    cleanupStudyMode = () => {
      window.removeEventListener("keydown", onKeyDown);
    };

    async function finish() {
      if (cleanupStudyMode) {
        cleanupStudyMode();
        cleanupStudyMode = null;
      }

      const seconds = Math.max(1, Math.round((Date.now() - start) / 1000));
      // send each card's id + result so the backend can record per-card stats
      const payload = results.map((knew, idx) => ({ card_id: cards[idx].id, knew: !!knew }));
      await api(studyUrl || ("/decks/" + deckId + "/study"), { method: "POST", body: { results: payload, seconds } });
      const acc = Math.round(100 * correct / cards.length);
      const missedCards = cards.filter((c, idx) => !results[idx]);
      const wrongNums = results.map((k, idx) => k ? null : idx + 1).filter(n => n != null);
      lastMissed = { deckId, cards: missedCards, name: deckName };
      const need = missedCards.length;
      app.innerHTML = `
        <div class="study-area view">
          <div class="result">
            <div class="big">🎉</div>
            <h2>Study Complete!</h2>
            <p class="sub">You reviewed ${escapeHtml(deckName)}.</p>
            <div class="result-grid">
              <div class="rg"><div class="v">${cards.length}</div><div class="l">Cards reviewed</div></div>
              <div class="rg"><div class="v">${correct}</div><div class="l">Correct answers</div></div>
              <div class="rg"><div class="v">${acc}%</div><div class="l">Accuracy</div></div>
              <div class="rg"><div class="v">${formatTime(seconds)}</div><div class="l">Study time</div></div>
            </div>
            ${need ? `<div class="need-practice">${need} card${need > 1 ? "s" : ""} to review again · question${wrongNums.length > 1 ? "s" : ""} <b>${wrongNums.join(", ")}</b></div>` : `<div class="need-practice" style="background:var(--ok)">Perfect score — no cards to review 🎉</div>`}
            <div style="margin-top:26px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
              <button class="btn btn-primary btn-lg" onclick="App.studyAgain(${deckId})">Study Again</button>
              ${need ? `<button class="btn btn-primary btn-lg" onclick="App.practiceMissed(${deckId})">Practice Missed (${need})</button>` : ""}
              <button class="btn btn-lg" onclick="location.hash='#/deck/${deckId}'">Back to Deck</button>
            </div>
          </div>
        </div>`;
    }

    showCard();
  }

  /* ================= QUIZ (multiple choice) ================= */
  // Build a question's options: the correct answer + up to 3 wrong answers
  // drawn from other cards' backs in the same deck.
  function quizOptions(cards, idx) {
    const correct = (cards[idx].back || "").trim();
    const seen = new Set([correct]);
    const opts = [{ text: correct, correct: true }];
    for (let j = 0; j < cards.length && opts.length < 4; j++) {
      if (j === idx) continue;
      const b = (cards[j].back || "").trim();
      if (b && !seen.has(b)) { seen.add(b); opts.push({ text: b, correct: false }); }
    }
    return shuffle(opts);
  }
  async function quizDeck(deckId) {
    const { ok, data } = await api("/decks/" + deckId);
    if (!ok || !data.deck || !data.deck.cards.length) {
      toast("This deck has no cards to quiz yet.", "error");
      return;
    }
    mountQuiz([...data.deck.cards], data.deck.name, deckId);
  }
  function mountQuiz(cards, name, deckId) {
    if (cleanupStudyMode) { cleanupStudyMode(); cleanupStudyMode = null; }
    app.innerHTML = `
      <div class="page-head">
        <a class="breadcrumb" href="#/deck/${deckId}" onclick="App.leaveStudy('#/deck/${deckId}');return false;">← Back to Deck</a>
        <div class="spacer"></div>
        <div class="muted" style="font-size:13.5px;font-weight:600" id="qCounter">Question 1 of ${cards.length}</div>
      </div>
      <div class="study-area view">
        <div class="study-progress" id="qProg"></div>
        <div class="quiz-card"><div class="hint">Pick the best answer</div><div class="quiz-q" id="qQ"></div></div>
        <div class="quiz-options" id="qOpts"></div>
        <div class="quiz-feedback" id="qFeedback"></div>
        <button class="btn btn-primary btn-lg hidden" id="qNext">Next →</button>
        <div style="margin-top:22px;color:var(--text-faint);font-size:12.5px;display:flex;gap:18px;flex-wrap:wrap;justify-content:center">
          <span><kbd class="k-hint">1</kbd>–<kbd class="k-hint">4</kbd> Pick an answer</span>
          <span><kbd class="k-hint">Enter</kbd> Next</span>
        </div>
      </div>`;
    runQuiz(cards, name, deckId);
  }
  function runQuiz(cards, deckName, deckId) {
    let i = 0, correct = 0;
    const results = [];
    const start = Date.now();
    let answered = false;
    const q = $("#qQ"), opts = $("#qOpts"), prog = $("#qProg"), counter = $("#qCounter"), next = $("#qNext"), fb = $("#qFeedback");

    function paintProg() {
      prog.innerHTML = cards.map((c, idx) =>
        `<i class="${idx < i ? (results[idx] ? "correct" : "wrong") : (idx === i ? "done" : "")}"></i>`
      ).join("");
      counter.textContent = `Question ${Math.min(i + 1, cards.length)} of ${cards.length}`;
    }
    function show() {
      answered = false;
      next.classList.add("hidden");
      fb.className = "quiz-feedback"; fb.textContent = "";
      const c = cards[i];
      q.textContent = c.front;
      const options = quizOptions(cards, i);
      opts.innerHTML = options.map((o, k) =>
        `<button class="quiz-opt" data-correct="${o.correct ? "1" : "0"}"><span class="k">${k + 1}</span><span>${escapeHtml(o.text)}</span></button>`
      ).join("");
      opts.querySelectorAll(".quiz-opt").forEach(b => b.onclick = () => pick(b));
      paintProg();
    }
    function pick(btn) {
      if (answered) return;
      answered = true;
      const isCorrect = btn.getAttribute("data-correct") === "1";
      if (isCorrect) correct++;
      results[i] = isCorrect;
      opts.querySelectorAll(".quiz-opt").forEach(b => {
        b.disabled = true;
        if (b.getAttribute("data-correct") === "1") b.classList.add("right");
        else if (b === btn) b.classList.add("wrong");
      });
      fb.className = "quiz-feedback " + (isCorrect ? "right" : "wrong");
      fb.textContent = isCorrect ? "✅ Correct!" : "❌ Not quite — the answer is: " + cards[i].back;
      next.classList.remove("hidden");
    }
    next.onclick = () => {
      i++;
      if (i >= cards.length) return finish();
      show();
    };
    function onKey(e) {
      const tag = e.target && e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!$("#authModal").classList.contains("hidden") || !$("#confirmModal").classList.contains("hidden")) return;
      if (!answered && /^[1-4]$/.test(e.key)) {
        const btns = opts.querySelectorAll(".quiz-opt");
        const n = +e.key - 1;
        if (btns[n]) { e.preventDefault(); pick(btns[n]); }
      } else if ((e.key === "Enter" || e.key === " ") && answered) {
        e.preventDefault();
        next.onclick();
      }
    }
    window.addEventListener("keydown", onKey);
    cleanupStudyMode = () => window.removeEventListener("keydown", onKey);

    async function finish() {
      if (cleanupStudyMode) { cleanupStudyMode(); cleanupStudyMode = null; }
      const seconds = Math.max(1, Math.round((Date.now() - start) / 1000));
      const payload = results.map((knew, idx) => ({ card_id: cards[idx].id, knew: !!knew }));
      await api("/decks/" + deckId + "/study", { method: "POST", body: { results: payload, seconds } });
      const acc = Math.round(100 * correct / cards.length);
      app.innerHTML = `<div class="study-area view"><div class="result">
        <div class="big">${acc === 100 ? "🏆" : "🎉"}</div>
        <h2>Quiz Complete!</h2>
        <p class="sub">You answered ${cards.length} question${cards.length > 1 ? "s" : ""}.</p>
        <div class="result-grid">
          <div class="rg"><div class="v">${cards.length}</div><div class="l">Questions</div></div>
          <div class="rg"><div class="v">${correct}</div><div class="l">Correct</div></div>
          <div class="rg"><div class="v">${acc}%</div><div class="l">Score</div></div>
          <div class="rg"><div class="v">${formatTime(seconds)}</div><div class="l">Time</div></div>
        </div>
        <div style="margin-top:26px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
          <button class="btn btn-primary btn-lg" onclick="App.quizDeck(${deckId})">Quiz Again</button>
          <button class="btn btn-lg" onclick="App.leaveStudy('#/deck/${deckId}')">Back to Deck</button>
        </div></div></div>`;
    }
    show();
  }

  /* ================= QUIZZES hub ================= */
  function renderQuizzes() {
    if (cleanupStudyMode) { cleanupStudyMode(); cleanupStudyMode = null; }
    app.innerHTML = `
      <div class="page-head"><h1>Quizzes</h1><div class="spacer"></div></div>
      <div class="view" style="max-width:800px;margin:0 auto">
        <div class="panel">
          <div class="section-title" style="margin-top:0">🧠 Create an AI quiz</div>
          <p class="section-sub">Memora's AI writes a fresh multiple-choice quiz on your subject. Your score is revealed only when you finish — no hints along the way.</p>
          <div class="field"><label>Subject</label>
            <div class="chips" id="qzSubject">${["English", "Math", "Science"].map(s => `<button class="chip${s === "Science" ? " active" : ""}" data-s="${s}">${s}</button>`).join("")}</div>
          </div>
          <div class="field"><label>Topic <span class="hint">(optional)</span></label>
            <input type="text" id="qzTopic" placeholder="e.g. Fractions, Cells, Grammar" /></div>
          <div class="field"><label>Number of questions · <span class="range-val" id="qzNumVal">5</span></label>
            <input type="range" id="qzNum" min="3" max="10" step="1" value="5" />
            <div class="range-scale"><span>3</span><span>6</span><span>10</span></div></div>
          <button class="btn btn-primary btn-lg btn-block" id="qzCreateBtn">✨ Generate Quiz</button>
          <div class="field-hint">The AI can take up to 45 seconds to craft your questions. You can make about one new quiz per minute.</div>
        </div>
        <div class="panel" style="margin-top:18px">
          <div class="section-title" style="margin-top:0">📚 Turn a deck into a quiz</div>
          <p class="section-sub">Pick one of your flashcard decks to play as a quiz.</p>
          <div id="qzDecks">${loaderHtml("Loading your decks…")}</div>
        </div>
        <div id="qzOut"></div>
      </div>`;
    let subject = "Science";
    chipBind("#qzSubject", "data-s", v => subject = v);
    const num = $("#qzNum");
    if (num) num.addEventListener("input", e => { const t = $("#qzNumVal"); if (t) t.textContent = e.target.value; });
    const btn = $("#qzCreateBtn");
    if (btn) btn.onclick = () => createAiQuiz(subject, $("#qzTopic").value.trim(), +num.value);
    loadDecksForQuiz();
  }

  async function loadDecksForQuiz() {
    const wrap = $("#qzDecks"); if (!wrap) return;
    const { data } = await api("/decks");
    const decks = data.decks || [];
    if (!decks.length) { wrap.innerHTML = `<div class="empty" style="padding:24px"><h3>No decks yet</h3><p>Create some flashcards first, then turn one into a quiz.</p></div>`; return; }
    wrap.innerHTML = `<div class="grid-decks">${decks.map(d => `
      <div class="deck">
        <div class="deck-emoji">${deckEmoji(d.subject)}</div>
        <div class="deck-subject">${escapeHtml(d.subject)}</div>
        <h3>${escapeHtml(d.name)}</h3>
        <div class="meta">${d.card_count || 0} cards</div>
        <button class="btn btn-primary btn-block" onclick="App.quizDeckAsQuiz(${d.id})">▶ Start Quiz</button>
      </div>`).join("")}</div>`;
  }

  async function createAiQuiz(subject, topic, number) {
    const out = $("#qzOut"); if (!out) return;
    out.innerHTML = loaderHtml("🧠 The AI is searching for quiz questions… (up to 45s)");
    const { ok, data } = await api("/quiz/generate", { method: "POST", body: { subject, topic, number } });
    if (!ok) { out.innerHTML = `<div class="empty"><div class="em">😕</div><h3>Couldn't create the quiz</h3><p>${escapeHtml(data.error || "Please try again.")}</p></div>`; return; }
    const quiz = data.quiz || [];
    if (!quiz.length) { out.innerHTML = `<div class="empty"><div class="em">🤔</div><h3>No questions came back</h3><p>Try again in a moment.</p></div>`; return; }
    out.innerHTML = "";
    startQuizSession(quiz, `${data.subject} quiz${topic ? " · " + topic : ""}`);
  }

  // Turn a library deck into a multiple-choice quiz session.
  async function quizDeckAsQuiz(deckId) {
    const { ok, data } = await api("/decks/" + deckId);
    if (!ok || !data.deck || !data.deck.cards.length) { toast("That deck has no cards yet.", "error"); return; }
    const cards = data.deck.cards;
    const questions = cards.map((c, idx) => {
      const opts = quizOptions(cards, idx);
      return { question: c.front, options: opts.map(o => o.text), answer: opts.find(o => o.correct).text };
    });
    startQuizSession(questions, data.deck.name + " quiz");
  }

  function startQuizSession(questions, title) {
    if (cleanupStudyMode) { cleanupStudyMode(); cleanupStudyMode = null; }
    app.innerHTML = `
      <div class="page-head">
        <a class="breadcrumb" href="#/quizzes" onclick="App.leaveStudy('#/quizzes');return false;">← Quizzes</a>
        <div class="spacer"></div>
        <div class="muted" style="font-weight:600" id="zsCounter">Question 1 of ${questions.length}</div>
      </div>
      <div class="study-area view">
        <div class="study-progress" id="zsProg"></div>
        <div class="quiz-card"><div class="hint">${escapeHtml(title)}</div><div class="quiz-q" id="zsQ"></div></div>
        <div class="quiz-options" id="zsOpts"></div>
        <button class="btn btn-primary btn-lg hidden" id="zsNext">Next →</button>
        <div style="margin-top:20px;color:var(--text-faint);font-size:12.5px;display:flex;gap:18px;justify-content:center">
          <span><kbd class="k-hint">1</kbd>–<kbd class="k-hint">4</kbd> Pick an answer</span>
          <span><kbd class="k-hint">Enter</kbd> Next</span>
        </div>
      </div>`;
    runQuizSession(questions, title);
  }

  function runQuizSession(questions, title) {
    let i = 0, correct = 0;
    const picked = [];
    let answered = false;
    const q = $("#zsQ"), opts = $("#zsOpts"), prog = $("#zsProg"), counter = $("#zsCounter"), next = $("#zsNext");

    function paintProg() {
      // Show progress in one uniform color (no right/wrong reveal before the end).
      prog.innerHTML = questions.map((c, idx) =>
        `<i class="${idx <= i ? "done" : ""}"></i>`
      ).join("");
      counter.textContent = `Question ${Math.min(i + 1, questions.length)} of ${questions.length}`;
    }
    function show() {
      answered = false;
      next.classList.add("hidden");
      const qu = questions[i];
      q.textContent = qu.question;
      const shuffled = shuffle(qu.options.map((t, idx) => ({ t, idx })));
      opts.innerHTML = shuffled.map((o, k) =>
        `<button class="quiz-opt" data-idx="${o.idx}"><span class="k">${k + 1}</span><span>${escapeHtml(o.t)}</span></button>`
      ).join("");
      opts.querySelectorAll(".quiz-opt").forEach(b => b.onclick = () => pick(b));
      paintProg();
    }
    function pick(btn) {
      if (answered) return;
      answered = true;
      opts.querySelectorAll(".quiz-opt").forEach(b => b.classList.remove("picked"));
      btn.classList.add("picked");
      picked[i] = questions[i].options[+btn.getAttribute("data-idx")];
      if (picked[i] === questions[i].answer) correct++;
      next.classList.remove("hidden");
    }
    next.onclick = () => { i++; if (i >= questions.length) return finish(); show(); };
    function onKey(e) {
      const tag = e.target && e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!$("#authModal").classList.contains("hidden") || !$("#confirmModal").classList.contains("hidden")) return;
      if (!answered && /^[1-4]$/.test(e.key)) {
        const bs = opts.querySelectorAll(".quiz-opt"); const n = +e.key - 1;
        if (bs[n]) { e.preventDefault(); pick(bs[n]); }
      } else if ((e.key === "Enter" || e.key === " ") && answered) { e.preventDefault(); next.onclick(); }
    }
    window.addEventListener("keydown", onKey);
    cleanupStudyMode = () => window.removeEventListener("keydown", onKey);

    function finish() {
      if (cleanupStudyMode) { cleanupStudyMode(); cleanupStudyMode = null; }
      const acc = Math.round(100 * correct / questions.length);
      const banner = questions.map((qu, idx) => {
        const user = picked[idx]; const right = user === qu.answer;
        return `<div class="qz-review ${right ? "right" : "wrong"}">
          <div class="qr-q">${escapeHtml(qu.question)}</div>
          <div class="qr-a">Your answer: <b>${escapeHtml(user ?? "—")}</b> · Correct: <b>${escapeHtml(qu.answer)}</b> ${right ? "✅" : "❌"}</div>
        </div>`;
      }).join("");
      app.innerHTML = `<div class="study-area view"><div class="result">
        <div class="big">${acc === 100 ? "🏆" : "🎉"}</div>
        <h2>Quiz Complete!</h2>
        <p class="sub">You answered ${questions.length} question${questions.length > 1 ? "s" : ""}.</p>
        <div class="result-grid">
          <div class="rg"><div class="v">${questions.length}</div><div class="l">Questions</div></div>
          <div class="rg"><div class="v">${correct}</div><div class="l">Correct</div></div>
          <div class="rg"><div class="v">${acc}%</div><div class="l">Score</div></div>
        </div>
        <div style="margin:24px 0;text-align:left" class="qz-review-list">${banner}</div>
        <div style="margin-top:18px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
          <button class="btn btn-primary btn-lg" onclick="App.leaveStudy('#/quizzes')">Back to Quizzes</button>
        </div></div></div>`;
    }
    show();
  }

  /* ================= STATS ================= */
  async function renderStats() {
    const { data } = await api("/stats");
    const daily = (data.daily || []).reduce((m, d) => { m[d.day] = (m[d.day] || 0) + d.seconds; return m; }, {});
    const todayStart = Math.floor(new Date().getTime() / 1000 / 86400);
    const days = 7, bars = [], labels = [];
    let max = 1;
    for (let k = days - 1; k >= 0; k--) {
      const day = todayStart - k, mins = Math.round((daily[day] || 0) / 60);
      if (mins > max) max = mins;
      bars.push(mins);
      labels.push(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][new Date(day * 86400 * 1000).getDay()]);
    }
    const minLabel = m => m > 0 ? (m >= 60 ? Math.floor(m / 60) + "h " + (m % 60) + "m" : m + " min") : "0 min";
    app.innerHTML = `
      <div class="page-head"><h1>Statistics</h1></div>
      <div class="stats-row">
        <div class="stat"><div class="label">Daily study time (7d)</div><div class="value">${formatTime(data.total_study_seconds || 0)}</div></div>
        <div class="stat"><div class="label">Cards reviewed</div><div class="value">${data.cards_reviewed || 0}</div></div>
        <div class="stat accent"><div class="label">Study streak</div><div class="value">🔥 ${data.study_streak || 0}</div><div class="sub">consecutive days</div></div>
        <div class="stat"><div class="label">Total study time</div><div class="value">⏱ ${formatTime((data.daily || []).reduce((a, d) => a + d.seconds, 0))}</div></div>
      </div>
      <div class="panel">
        <div class="section-title" style="margin-top:0">Study activity</div>
        <div class="section-sub">Minutes studied per day · hover a bar for details</div>
        <div class="chart-bars" style="margin-top:14px">${bars.map(b => `<div class="bar ${b ? "has" : ""}" style="height:${b ? Math.max(6, 100 * b / max) : 2}%" title=""><span class="tip">${minLabel(b)}</span></div>`).join("")}</div>
        <div class="chart-labels">${labels.map(l => `<span>${l}</span>`).join("")}</div>
      </div>`;
  }

  /* ---------------- auth gate ---------------- */
  function renderAuthGate() {
    app.innerHTML = `<div class="empty view"><div class="em">🔐</div><h3>Sign in to continue</h3>
      <p>Your decks, study progress, and streaks are tied to your account.</p>
      <button class="btn btn-primary btn-lg" onclick="App.openAuth()">Sign In</button></div>`;
  }

  /* ---------------- boot ---------------- */
  function boot() {
    initTheme();
    initAuthModal();
    initChangelog();
    initConfirm();
    initImport();
    ensureImportModal();
    document.addEventListener("click", closeSelects);
    api("/version").then(({ data }) => {
      if (data && data.version) $("#appVersion").textContent = "v" + data.version.split(".").slice(0, 2).join(".");
    });
    route();
  }
  window.addEventListener("load", boot);

  // public API for inline handlers
  window.App = {
    openAuth,
    toggleFav,
    deleteDeckConfirm,
    renameDeck,
    addCardForm,
    saveNewCard,
    editCard,
    saveEditCard,
    delCard,
    regenCard,
    renderDeckNow: renderDeck,
    downloadDeck,
    openImport,
    createImportDeck,
    quizDeck,
    quizDeckAsQuiz,
    studyAgain: renderStudy,
    practiceWeak,
    practiceMissed,
    smartReview,
    smartReviewAll,
    leaveStudy,
    cycleMood,
    loadDemo: tryDemo,
    startDemo: tryDemo,
  };
  window.tryDemo = tryDemo;
})();