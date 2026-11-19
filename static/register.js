// Register page: the AI fills in the form from a photo; the person checks it and presses Register.
// The photo comes from the scanning station (ESP32 camera + scale) or from this device.
const form = document.getElementById('register');
const $ = id => document.getElementById(id);
const field = name => form.elements[name];

function status(msg, bad) { $('ai-status').textContent = msg; $('ai-status').className = 'note ' + (bad ? 'err' : ''); }
function showDetails() { $('details').hidden = false; }

// Put the AI's answer into the form and say how sure it is.
function fill(r, extra = '') {
  for (const k of ['category', 'material', 'name', 'size', 'use', 'location',
                   'colour', 'condition', 'transparency', 'description']) field(k).value = r[k] || '';
  const pct = Math.round(r.confidence * 100);
  status((r.material
    ? `AI thinks: ${r.name} (${r.material}, ${pct}% sure). ` +
      (r.unsure ? 'It is not sure. Please check the material.' : 'Check the details below, then press Register.')
    : 'The AI could not tell the material. Please fill it in.') + (extra ? ' ' + extra : ''), r.unsure || !r.material);
  showDetails();
}

// Show the photo the AI is looking at (from this device or from the station).
let previewUrl = null;
function showPreview(src) {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = src.startsWith('blob:') ? src : null;
  $('preview').src = src; $('preview').hidden = $('preview-note').hidden = false;
}

$('manual').onclick = () => { showDetails(); field('material').focus(); };
$('photo').onchange = () => {                      // preview, then start the AI straight away
  if (!$('photo').files.length) return;
  showPreview(URL.createObjectURL($('photo').files[0]));
  $('identify').click();
};

$('identify').onclick = async () => {
  if (!$('photo').files.length) return status('Choose or take a photo first.', true);
  const body = new FormData();
  body.append('photo', $('photo').files[0]);
  if ($('weight').value) body.append('weight_g', $('weight').value);
  field('photo_token').value = '';                  // this photo replaces any station photo
  $('identify').disabled = true;
  status('Identifying… (up to about 30 seconds)');
  try {
    const r = await (await fetch('/api/identify', { method: 'POST', body })).json();
    if (!r.ok) { status(r.error, true); return showDetails(); }
    fill(r);
  } catch (e) {
    status('Could not reach the server. Fill in the details by hand.', true); showDetails();
  } finally { $('identify').disabled = false; }
};

// ---- scanning station: arm it, then wait for the ESP32 to send the next piece ----
let waiting = false, run = 0;                     // run: ignore loops from earlier presses
const sleep = ms => new Promise(ok => setTimeout(ok, ms));

async function stopStation(msg, bad) {
  waiting = false;
  $('station').textContent = '⚖️ Use scanning station';
  await fetch('/api/station/cancel', { method: 'POST' }).catch(() => {});
  if (msg) status(msg, bad);
}

$('station').onclick = async () => {
  if (waiting) return stopStation('Cancelled.');
  try { await fetch('/api/station/arm', { method: 'POST' }); }
  catch (e) { return status('Could not reach the server.', true); }
  waiting = true; const mine = ++run;
  $('station').textContent = 'Cancel';
  status('Waiting… put the item on the scale and keep it still (2 minutes).');
  while (waiting) {
    await sleep(1500);
    if (!waiting || mine !== run) return;
    let r;
    try { r = await (await fetch('/api/station/capture')).json(); }
    catch (e) { continue; }                         // server busy or restarting: keep trying
    if (mine !== run) return;
    if (r.waiting) continue;
    waiting = false;
    $('station').textContent = '⚖️ Use scanning station';
    if (!r.photo_token) return status('Timed out: no item came from the station. Press the button again.', true);
    return identifyStationPhoto(r.photo_token, r.weight_g);
  }
};

async function identifyStationPhoto(token, weight) {
  field('photo_token').value = token;               // station photo is saved with the item
  showPreview(`/static/scans/pending_${token}.jpg`);
  if (weight != null) $('weight').value = weight;
  $('photo').value = '';
  status(`Photo received (${weight} g). You can take the item off the scale. Identifying… (up to about 30 seconds)`);
  const body = new FormData();
  body.append('photo_token', token);
  if (weight != null) body.append('weight_g', weight);
  $('station').disabled = $('identify').disabled = true;
  try {
    const r = await (await fetch('/api/station/identify', { method: 'POST', body })).json();
    if (!r.ok) { status(r.error, true); return showDetails(); }
    fill(r, (r.measured ? 'Size measured on the board.' : r.note || '') + ` Weight ${weight} g.`);
  } catch (e) {
    status('Could not reach the server. Fill in the details by hand.', true); showDetails();
  } finally { $('station').disabled = $('identify').disabled = false; }
}

// Leaving the page while waiting: release the station so it sorts normally again.
addEventListener('pagehide', () => { if (waiting) navigator.sendBeacon('/api/station/cancel'); });
