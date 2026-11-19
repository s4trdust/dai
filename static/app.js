// Shared by every page: theme toggle, eco points & levels, toasts and confetti.
// Points live in this browser only (localStorage) - there are no user accounts.
// Pages award points with <body data-award="10:donated"> or a ?pts=15&kind=taken redirect.
(function () {
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };
  const el = id => document.getElementById(id);
  const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- theme ----
  el('themeBtn').onclick = () => {
    const cur = document.documentElement.dataset.theme ||
                (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    store.set('rs_theme', next);
  };

  // ---- toast + confetti ----
  function toast(msg) {
    const t = el('rsToast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 2800);
  }
  function confetti(n = 70) {
    if (reduceMotion()) return;
    const cols = ['#5b3fd6', '#ff6b4a', '#ffc23d', '#22a06b', '#38b2d8', '#a593ff'];
    for (let i = 0; i < n; i++) {
      const s = document.createElement('i'); s.className = 'confetti';
      s.style.left = Math.random() * 100 + 'vw'; s.style.background = cols[i % cols.length];
      s.style.setProperty('--x', (Math.random() * 200 - 100) + 'px');
      s.style.setProperty('--r', (Math.random() * 900 - 450) + 'deg');
      s.style.setProperty('--d', (1.2 + Math.random() * 1.3) + 's');
      s.style.animationDelay = Math.random() * .25 + 's';
      document.body.appendChild(s); setTimeout(() => s.remove(), 3000);
    }
  }

  // ---- points & levels ----
  const LEVELS = [[0, 'Scrap Rookie'], [50, 'Tinkerer'], [150, 'Upcycler'], [300, 'Remix Master'], [600, 'Re:Source Legend']];
  const profile = Object.assign({ pts: 0, donated: 0, taken: 0, quizBest: 0 }, store.get('rs_profile', {}));
  const saveProfile = () => store.set('rs_profile', profile);
  const levelOf = p => { let i = 0; LEVELS.forEach(([min], j) => { if (p >= min) i = j; }); return i; };

  function renderPill() {
    const i = levelOf(profile.pts), next = LEVELS[i + 1];
    el('lvNum').textContent = i + 1; el('lvName').textContent = LEVELS[i][1]; el('lvPts').textContent = profile.pts;
    el('lvBar').style.width = next ? ((profile.pts - LEVELS[i][0]) / (next[0] - LEVELS[i][0]) * 100) + '%' : '100%';
  }

  // kind: 'donated' or 'taken' also counts towards those totals
  function addPts(n, kind) {
    if (!(n > 0)) return;
    const before = levelOf(profile.pts);
    profile.pts += n;
    if (kind === 'donated' || kind === 'taken') profile[kind]++;
    saveProfile(); renderPill();
    const pill = el('lvlBtn'), r = pill.getBoundingClientRect();
    pill.classList.remove('bump'); void pill.offsetWidth; pill.classList.add('bump');
    if (!reduceMotion()) {
      const f = document.createElement('div'); f.className = 'float-pts'; f.textContent = '+' + n;
      f.style.left = (r.left + r.width / 2 - 12) + 'px'; f.style.top = (r.bottom + 4) + 'px';
      document.body.appendChild(f); setTimeout(() => f.remove(), 1200);
    }
    const after = levelOf(profile.pts);
    if (after > before) setTimeout(() => { confetti(120); toast(`🎉 Level up! You're now a ${LEVELS[after][1]}`); }, 300);
  }

  const dlg = el('rsDlg');
  dlg.addEventListener('click', e => { if (e.target === dlg || e.target.closest('[data-close]')) dlg.close(); });
  el('lvlBtn').onclick = () => {
    const i = levelOf(profile.pts);
    el('rsDlgInner').innerHTML = `<div class="modal-head"><div><span class="note">Your eco level</span><h2>🌱 ${LEVELS[i][1]}</h2></div>
        <button type="button" class="icon-btn" data-close aria-label="Close">✕</button></div>
      <div class="modal-body">
        <div class="stats" style="grid-template-columns:repeat(3,1fr);margin-bottom:8px">
          <div class="stat"><b>${profile.pts}</b><span>points</span></div>
          <div class="stat"><b>${profile.donated}</b><span>items donated</span></div>
          <div class="stat"><b>${profile.taken}</b><span>items reused</span></div>
        </div>
        <p class="note" style="margin:4px 0">Sort game best: ${profile.quizBest}/10 · Points are saved in this browser only.</p>
        <div class="ladder">${LEVELS.map(([min, n], j) =>
          `<div class="${j === i ? 'cur' : j > i ? 'locked' : ''}"><span>${j > i ? '🔒' : j === i ? '⭐' : '✅'} ${n}</span><span>${min} pts</span></div>`).join('')}</div>
      </div>`;
    dlg.showModal();
  };

  renderPill();

  // points handed out by the page that was just shown
  const award = document.body.dataset.award;
  if (award) { const [n, kind] = award.split(':'); setTimeout(() => { addPts(+n, kind); confetti(50); }, 300); }
  const url = new URL(location.href);
  if (url.searchParams.has('pts')) {
    const n = +url.searchParams.get('pts'), kind = url.searchParams.get('kind');
    url.searchParams.delete('pts'); url.searchParams.delete('kind');
    history.replaceState(null, '', url);               // so a refresh does not award them again
    setTimeout(() => { addPts(n, kind); confetti(50); }, 300);
  }

  window.RS = { toast, confetti, addPts, profile, saveProfile };
})();
