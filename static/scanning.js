const $ = id => document.getElementById(id);
let scanner = null, running = false;

function status(msg, bad) { $('status').textContent = msg; $('status').className = 'note ' + (bad ? 'err' : ''); }

async function stopCamera() {
  if (scanner && running) { try { await scanner.stop(); } catch (e) {} }
  running = false; $('toggle').textContent = 'Start camera';
}

async function lookup(code) {
  code = String(code).trim();
  const res = await fetch('/api/item/' + encodeURIComponent(code));
  const data = await res.json();
  $('result').textContent = '';
  if (!data.ok) return status(data.error, true);
  status('');
  const it = data.item, box = document.createElement('div');
  box.className = 'card';
  const h = document.createElement('h3'); h.textContent = it.name;
  const p = document.createElement('p');
  p.textContent = `${it.material} · ${it.category_label} · ${it.quantity} units · ${it.size} · 📍 ${it.location}` +
                  (it.status === 'recycle' ? ' · marked to be recycled' : '');
  const qty = document.createElement('input');      // how many to take (only shown if more than 1)
  Object.assign(qty, { type: 'number', min: 1, max: it.quantity, value: 1 });
  qty.setAttribute('aria-label', 'How many');
  const btn = document.createElement('button'); btn.className = 'primary'; btn.textContent = 'Confirm: I am taking this';
  btn.onclick = async () => {                       // "checkout" – lowers the quantity, removes the item at 0
    btn.disabled = true;
    const r = await (await fetch('/checkout', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                body: JSON.stringify({ id: it.id, quantity: +qty.value || 1 }) })).json();
    $('result').textContent = '';
    status(!r.ok ? (r.error || 'Failed.') : r.left ? `Done – took ${r.taken} × ${it.name}, ${r.left} left.`
                                                   : `Done – ${it.name} removed from the library.`, !r.ok);
    if (r.ok && window.RS) { RS.addPts(15, 'taken'); RS.confetti(); }   // eco points for reusing it
  };
  box.append(h, p);
  if (it.quantity > 1) box.append(qty);
  box.append(btn); $('result').append(box);
}

$('lookup').onclick = () => $('code').value && lookup($('code').value);
$('code').onkeydown = e => { if (e.key === 'Enter') $('lookup').click(); };

$('toggle').onclick = async () => {
  if (running) return stopCamera();
  try {
    scanner = scanner || new Html5Qrcode('reader', { formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE] });
    await scanner.start({ facingMode: 'environment' }, { fps: 10, qrbox: { width: 250, height: 250 } },
      async text => { await stopCamera(); lookup(text); }, () => {});
    running = true; $('toggle').textContent = 'Stop camera'; status('Scanning…');
  } catch (e) { status('Could not start the camera (permission or HTTPS needed). Enter the code instead.', true); }
};
