/* ═══════════════════════════════════════════════
   KRYPTAN ACADEMY — Core JS Logic
   Progress, Navigation, TG WebApp integration
   ═══════════════════════════════════════════════ */

'use strict';

// ── Telegram WebApp ──
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor('#050508');
  tg.setBackgroundColor('#050508');
}

// ── Constants ──
const TESTS = [
  { key: 'holland',       title: 'Голланда',      emoji: '🎯', url: 'tests/holland.html' },
  { key: 'gambling',      title: 'Игромания',      emoji: '🎲', url: 'tests/gambling.html' },
  { key: 'hardiness',     title: 'Жизнестойкость', emoji: '🛡️', url: 'tests/hardiness.html' },
  { key: 'proforientation', title: 'Профориент.', emoji: '🔭', url: 'tests/proforientation.html' },
  { key: 'tolerance',     title: 'Толерантность',  emoji: '⚖️', url: 'tests/tolerance.html' },
];

const STORAGE_KEY = 'ka_progress_v2';

// ── Progress Storage ──
const Progress = {
  get() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch { return {}; }
  },
  set(data) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  },
  saveTest(key, result) {
    const p = this.get();
    p[key] = result;
    p[key + '_time'] = Date.now();
    this.set(p);
  },
  isComplete(key) {
    return !!this.get()[key];
  },
  allComplete() {
    return TESTS.every(t => this.isComplete(t.key));
  },
  getCompletedCount() {
    return TESTS.filter(t => this.isComplete(t.key)).length;
  },
};

// ── Navigation ──
function goToTest(testKey) {
  const test = TESTS.find(t => t.key === testKey);
  if (!test) return;
  window.location.href = test.url;
}

function goToNextTest() {
  const p = Progress.get();
  const next = TESTS.find(t => !p[t.key]);
  if (next) {
    window.location.href = next.url;
  } else {
    window.location.href = '../result.html';
  }
}

function goHome() {
  // Find relative path to index
  const depth = window.location.pathname.split('/').length - 1;
  const back = depth > 2 ? '../' : './';
  window.location.href = back + 'index.html';
}

// ── Render Steps ──
function renderSteps(containerId, currentKey) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const p = Progress.get();

  el.innerHTML = TESTS.map(t => {
    let cls = 'locked';
    if (p[t.key]) cls = 'done';
    else if (t.key === currentKey) cls = 'active';
    else {
      // Can unlock if previous is done
      const idx = TESTS.findIndex(x => x.key === t.key);
      const prevDone = idx === 0 || p[TESTS[idx-1].key];
      if (prevDone) cls = '';
    }
    return `
      <div class="step-item ${cls}">
        <div class="step-icon">${p[t.key] ? '✅' : t.emoji}</div>
        <span class="step-label">${t.title}</span>
      </div>`;
  }).join('');
}

// ── Render Progress Bar ──
function renderProgressBar(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const done = Progress.getCompletedCount();
  const pct = Math.round((done / TESTS.length) * 100);
  el.innerHTML = `
    <div class="progress-section">
      <div class="progress-label">
        <span class="progress-title">Прогресс отбора</span>
        <span class="progress-count">${done}/${TESTS.length}</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" style="width:${pct}%"></div>
      </div>
    </div>`;
}

// ── Toast ──
function showToast(msg, duration = 2500) {
  let t = document.querySelector('.toast');
  if (!t) {
    t = document.createElement('div');
    t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

// ── Send to Bot ──
async function sendResultsToBot(data) {
  if (!tg) return;
  try {
    tg.sendData(JSON.stringify(data));
  } catch(e) {
    console.warn('TG sendData failed', e);
  }
}

// ── Question Counter in test ──
function updateQuestionProgress(current, total, barId, countId) {
  const bar = document.getElementById(barId);
  const cnt = document.getElementById(countId);
  if (bar) bar.style.width = `${(current / total * 100).toFixed(1)}%`;
  if (cnt) cnt.textContent = `${current}/${total}`;
}
