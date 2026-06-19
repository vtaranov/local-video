const video = document.getElementById("video");
const langSelect = document.getElementById("lang-select");
const autoscrollBtn = document.getElementById("autoscroll-btn");
const searchInput = document.getElementById("search-input");
const searchCount = document.getElementById("search-count");
const cuesEl = document.getElementById("cues");
const titleEl = document.getElementById("title");
const summaryEl = document.getElementById("summary");
const homeBtn = document.getElementById("home-btn");
const libSection = document.getElementById("library");
const playerView = document.getElementById("player-view");
const libGrid = document.getElementById("lib-grid");
const libForm = document.getElementById("lib-form");
const libInput = document.getElementById("lib-input");
const libMsg = document.getElementById("lib-msg");

let cues = [];          // {start, end, text, el}
let activeIndex = -1;
let autoscroll = true;
let summaryByFile = {}; // имя .vtt -> имя .summary.md (или null)

// --- разбор времени VTT: "HH:MM:SS.mmm" или "MM:SS.mmm" -> секунды ---
function parseTime(t) {
  const parts = t.trim().split(":");
  let s = 0;
  for (const p of parts) s = s * 60 + parseFloat(p.replace(",", "."));
  return s;
}

function fmtTime(sec) {
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

// --- парсер WebVTT: возвращает массив реплик ---
function parseVTT(text) {
  const out = [];
  const blocks = text.replace(/\r/g, "").split(/\n\n+/);
  const timeRe = /(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}/;
  for (const block of blocks) {
    const lines = block.split("\n");
    const idx = lines.findIndex((l) => timeRe.test(l));
    if (idx === -1) continue;
    const [a, b] = lines[idx].split("-->");
    const start = parseTime(a);
    const end = parseTime(b.trim().split(" ")[0]);
    const raw = lines
      .slice(idx + 1)
      .join(" ")
      .replace(/<[^>]+>/g, "")          // убрать теги <c>, <00:00:00.000> и пр.
      .replace(/\s+/g, " ")
      .trim();
    if (!raw) continue;
    // склейка дублей подряд (частое в авто-субтитрах)
    if (out.length && out[out.length - 1].text === raw) {
      out[out.length - 1].end = end;
      continue;
    }
    out.push({ start, end, text: raw });
  }
  return out;
}

function renderCues() {
  cuesEl.innerHTML = "";
  if (!cues.length) {
    cuesEl.innerHTML = '<div class="empty">Транскрипт пуст</div>';
    return;
  }
  const frag = document.createDocumentFragment();
  cues.forEach((c, i) => {
    const el = document.createElement("div");
    el.className = "cue";
    el.dataset.i = i;
    el.innerHTML =
      `<span class="cue-time">${fmtTime(c.start)}</span>` +
      `<span class="cue-text"></span>`;
    el.querySelector(".cue-text").textContent = c.text;
    el.addEventListener("click", () => {
      video.currentTime = c.start;
      video.play();
    });
    c.el = el;
    frag.appendChild(el);
  });
  cuesEl.appendChild(frag);
  activeIndex = -1;
  applySearch();
}

function highlight(i) {
  if (i === activeIndex) return;
  if (activeIndex >= 0 && cues[activeIndex]?.el)
    cues[activeIndex].el.classList.remove("active");
  activeIndex = i;
  if (i < 0) return;
  const el = cues[i].el;
  el.classList.add("active");
  if (autoscroll) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

// бинарный поиск текущей реплики по времени
function findCue(t) {
  let lo = 0, hi = cues.length - 1, res = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (cues[mid].start <= t) { res = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  if (res >= 0 && t > cues[res].end + 0.5 && (res + 1 >= cues.length || t < cues[res + 1].start))
    return res; // в паузе между репликами — держим предыдущую
  return res;
}

video.addEventListener("timeupdate", () => {
  if (!cues.length) return;
  highlight(findCue(video.currentTime));
});

autoscrollBtn.addEventListener("click", () => {
  autoscroll = !autoscroll;
  autoscrollBtn.classList.toggle("on", autoscroll);
  autoscrollBtn.classList.toggle("off", !autoscroll);
  if (autoscroll && activeIndex >= 0)
    cues[activeIndex].el.scrollIntoView({ behavior: "smooth", block: "center" });
});

// --- поиск ---
function applySearch() {
  const q = searchInput.value.trim().toLowerCase();
  let hits = 0;
  for (const c of cues) {
    if (!c.el) continue;
    const textEl = c.el.querySelector(".cue-text");
    if (!q) {
      textEl.textContent = c.text;
      c.el.style.display = "";
      continue;
    }
    const match = c.text.toLowerCase().includes(q);
    c.el.style.display = match ? "" : "none";
    if (match) {
      hits++;
      const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
      textEl.innerHTML = c.text.replace(re, "<mark>$1</mark>");
    }
  }
  searchCount.textContent = q ? `${hits}` : "";
}
searchInput.addEventListener("input", applySearch);

async function loadTrack(file) {
  searchInput.value = "";
  const res = await fetch(`/media/${encodeURIComponent(file)}`);
  const text = await res.text();
  cues = parseVTT(text);
  renderCues();
}

// --- саммари (Markdown) ---
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// таймкоды MM:SS / H:MM:SS -> кликабельный span с секундами
function linkTimecodes(html) {
  return html.replace(/\b(\d{1,2}):([0-5]\d)(?::([0-5]\d))?\b/g, (m, a, b, c) => {
    const secs = c === undefined
      ? (+a) * 60 + (+b)
      : (+a) * 3600 + (+b) * 60 + (+c);
    return `<span class="ts" data-secs="${secs}">${m}</span>`;
  });
}

function inlineMd(text) {
  let h = escapeHtml(text);
  h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/\*(.+?)\*/g, "<em>$1</em>");
  return linkTimecodes(h);
}

function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];
  let inList = false;
  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };

  for (const line of lines) {
    const t = line.trim();
    if (!t) { closeList(); continue; }

    let m;
    if ((m = t.match(/^(#{1,3})\s+(.*)$/))) {
      closeList();
      const lvl = m[1].length;
      out.push(`<h${lvl}>${inlineMd(m[2])}</h${lvl}>`);
    } else if ((m = t.match(/^[*-]\s+(.*)$/))) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inlineMd(m[1])}</li>`);
    } else if (/^\*[^*].*\*$/.test(t)) {
      closeList();
      out.push(`<p class="subtle">${inlineMd(t.slice(1, -1))}</p>`);
    } else {
      closeList();
      out.push(`<p>${inlineMd(t)}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}

async function loadSummary(file) {
  if (!file) {
    summaryEl.innerHTML = "";
    return;
  }
  const res = await fetch(`/media/${encodeURIComponent(file)}`);
  if (!res.ok) { summaryEl.innerHTML = ""; return; }
  summaryEl.innerHTML = renderMarkdown(await res.text());
  summaryEl.scrollTop = 0;
}

summaryEl.addEventListener("click", (e) => {
  const ts = e.target.closest(".ts");
  if (!ts) return;
  video.currentTime = Number(ts.dataset.secs);
  video.play();
});

function applyMedia(data) {
  if (!data.video) {
    titleEl.textContent = "Видео не найдено";
    document.title = "Видеоплеер";
    video.removeAttribute("src");
    video.load();
    cues = [];
    cuesEl.innerHTML = '<div class="empty">В этой папке нет видео</div>';
    langSelect.innerHTML = "";
    langSelect.disabled = true;
    return;
  }

  titleEl.textContent = data.video.title;
  document.title = data.video.title;
  video.src = `/media/${encodeURIComponent(data.video.file)}`;

  langSelect.innerHTML = "";
  langSelect.disabled = !data.tracks.length;
  summaryByFile = {};
  if (!data.tracks.length) {
    cues = [];
    cuesEl.innerHTML = '<div class="empty">Транскрипты не найдены</div>';
    summaryEl.innerHTML = "";
    return;
  }
  for (const t of data.tracks) {
    summaryByFile[t.file] = t.summary;
    const opt = document.createElement("option");
    opt.value = t.file;
    opt.textContent = t.label;
    langSelect.appendChild(opt);
  }
  selectTrack(data.tracks[0].file);
}

function selectTrack(file) {
  loadTrack(file);
  loadSummary(summaryByFile[file]);
}

langSelect.addEventListener("change", () => selectTrack(langSelect.value));

// --- библиотека / переключение видов ---
function showLibrary(data) {
  libInput.value = data.library || "";
  libGrid.innerHTML = "";
  if (!data.videos || !data.videos.length) {
    libGrid.innerHTML = '<div class="empty">В библиотеке пока нет видео</div>';
  } else {
    const frag = document.createDocumentFragment();
    for (const v of data.videos) {
      const card = document.createElement("button");
      card.className = "lib-card";
      card.innerHTML =
        `<span class="lib-title"></span>` +
        `<span class="lib-langs">${v.langs.map((l) => `<span class="tag">${l}</span>`).join("")}</span>`;
      card.querySelector(".lib-title").textContent = v.title;
      card.addEventListener("click", () => openVideo(v.dir));
      frag.appendChild(card);
    }
    libGrid.appendChild(frag);
  }
  titleEl.textContent = "Библиотека";
  document.title = "Библиотека";
  homeBtn.classList.add("hidden");
  playerView.classList.add("hidden");
  libSection.classList.remove("hidden");
}

function showPlayer(data) {
  libSection.classList.add("hidden");
  playerView.classList.remove("hidden");
  homeBtn.classList.remove("hidden");
  applyMedia(data);
}

async function openVideo(dir) {
  const res = await fetch("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir }),
  });
  const data = await res.json();
  if (res.ok) showPlayer(data);
}

async function goHome() {
  const data = await (await fetch("/api/home", { method: "POST" })).json();
  // остановить воспроизведение при выходе в список
  video.pause();
  showLibrary(data);
}

homeBtn.addEventListener("click", goHome);

libForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const path = libInput.value.trim();
  if (!path) return;
  libMsg.textContent = "…";
  libMsg.className = "";
  const res = await fetch("/api/library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const data = await res.json();
  if (!res.ok) {
    libMsg.textContent = data.error || "Ошибка";
    libMsg.className = "err";
    return;
  }
  libMsg.textContent = "";
  showLibrary(data);
}, false);

async function init() {
  const media = await (await fetch("/api/media")).json();
  if (media.current && media.video !== undefined) {
    // плеер запущен с конкретной папкой (--dir)
    showPlayer(media);
  } else {
    const lib = await (await fetch("/api/library")).json();
    showLibrary(lib);
  }
}

init();
