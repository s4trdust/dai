// "Where does it go?" sort game. Answers follow the real sorting rules (station/config.py).
(function () {
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ANS = { section: '🗃️ Storage section', shelf: '🏷️ Shelf + QR label', away: '🚫 Not accepted here', manual: '🔍 Manual area' };
  const QUIZ = [
    { e: '💎', n: 'A handful of small acrylic offcuts', a: 'section', why: 'Small acrylic goes into Section 1 and is only counted.' },
    { e: '📦', n: 'Small cardboard scraps', a: 'section', why: 'Small cardboard goes into Section 2.' },
    { e: '🧵', n: 'A 50 cm coil of wire', a: 'section', why: 'Wire always goes to Section 3, however long: it coils up to fit.' },
    { e: '🧩', n: 'A small failed 3D print', a: 'section', why: 'Small PLA pieces go into Section 4.' },
    { e: '🪵', n: 'A big sheet of plywood', a: 'shelf', why: 'Anything over 10 × 10 cm is a large item: it gets a shelf spot and a QR label.' },
    { e: '🔌', n: 'A working Arduino', a: 'shelf', why: 'Working electronics are unique items: shelved and tracked with a QR label.' },
    { e: '⚙️', n: 'A servo motor', a: 'shelf', why: 'Motors are unique items, so they get a QR label and a shelf spot.' },
    { e: '📏', n: 'A 1 m PVC pipe', a: 'shelf', why: 'Long stock is a large item with a QR label.' },
    { e: '🪵', n: 'A small wood offcut', a: 'manual', why: 'Small pieces with no section of their own are counted in the manual area.' },
    { e: '🛸', n: 'A mystery gadget the AI is not sure about', a: 'manual', why: 'When the AI isn\'t sure, a person checks it in the manual area.' },
    { e: '🔋', n: 'A power bank', a: 'away', why: 'Batteries go to the e-waste bin opposite Insta Chef, never into scrap storage.' },
    { e: '🔥', n: 'A burnt circuit board', a: 'away', why: 'Damaged electronics go to the school e-waste collection point.' },
    { e: '📚', n: 'An old textbook', a: 'away', why: 'Textbooks have their own collection point.' },
    { e: '🧸', n: 'A plushie', a: 'away', why: 'Plushies have their own collection point.' },
    { e: '💧', n: 'A leaking glue bottle', a: 'away', why: 'Leaking or contaminated items: stop and find the staff in charge.' },
  ];
  const el = document.getElementById('game');
  let game = null;

  function start() {
    game = { pool: [...QUIZ].sort(() => Math.random() - .5).slice(0, 10), i: 0, score: 0, streak: 0, answered: false };
    render();
  }

  function render() {
    const best = RS.profile.quizBest;
    if (!game) {
      el.innerHTML = `<div class="card q-card"><div class="q-emoji">🗂️</div><h3>Ready to sort?</h3>
        <p class="muted">10 objects. Choose where each one goes.<br>Your best: <b>${best}/10</b></p>
        <button type="button" class="btn fun" id="gStart">▶ Start game</button></div>`;
      document.getElementById('gStart').onclick = start; return;
    }
    if (game.i >= game.pool.length) {
      const s = game.score;
      const msg = s === 10 ? 'Perfect! You could run the scrapyard 🏆' : s >= 8 ? 'Great sorting! 🌟'
                : 'Check the Guide for the rules 📖';
      if (s > best) { RS.profile.quizBest = s; RS.saveProfile(); }
      el.innerHTML = `<div class="card q-card"><div class="q-emoji">${s >= 8 ? '🎉' : '🙂'}</div><h3>You scored ${s}/10</h3>
        <p class="muted">${msg}<br>Best: <b>${RS.profile.quizBest}/10</b></p>
        <button type="button" class="btn fun" id="gStart">↻ Play again</button></div>`;
      document.getElementById('gStart').onclick = start;
      if (s >= 8) RS.confetti(100);
      return;
    }
    const q = game.pool[game.i];
    el.innerHTML = `<div class="hud"><span>Round ${game.i + 1}/10</span><span class="streak">${game.streak > 1 ? '🔥 ' + game.streak + ' in a row' : ''}</span><span>Score ${game.score}</span></div>
      <div class="progress"><i style="width:${game.i * 10}%"></i></div>
      <div class="card q-card"><div class="q-emoji">${q.e}</div><h3>${esc(q.n)}</h3><p class="muted" style="margin:0">Where does it go?</p>
        <div class="answers">${Object.entries(ANS).map(([k, v]) => `<button type="button" class="ans" data-a="${k}">${v}</button>`).join('')}</div>
        <div id="gWhy" style="margin-top:14px"></div></div>`;
    game.answered = false;
    el.querySelectorAll('.ans').forEach(b => b.onclick = () => answer(b.dataset.a));
  }

  function answer(a) {
    if (game.answered) return;
    game.answered = true;
    const q = game.pool[game.i], ok = a === q.a;
    el.querySelectorAll('.ans').forEach(b => {
      b.disabled = true;
      if (b.dataset.a === q.a) b.classList.add('right'); else if (b.dataset.a === a) b.classList.add('wrong');
    });
    if (ok) { game.score++; game.streak++; RS.addPts(5); } else game.streak = 0;
    document.getElementById('gWhy').innerHTML = `<div class="alert ${ok ? 'ok' : 'warn'}" style="text-align:left">
        <h3>${ok ? '✅ Correct!' : '❌ Not quite'}</h3><p style="margin:0">${esc(q.why)}</p></div>
      <button type="button" class="btn primary" id="gNext" style="margin-top:10px">${game.i === 9 ? 'See results' : 'Next ›'}</button>`;
    const next = document.getElementById('gNext');
    next.onclick = () => { game.i++; render(); };
    next.focus();
  }

  render();
})();
