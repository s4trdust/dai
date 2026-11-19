// Register page: the person uploads a photo, and the AI fills in the form from it; the person
// checks it and presses Register. The weight comes from the station's scale, but only when the
// "Get weight from scale" button is pressed.
const form = document.getElementById('register');
const $ = id => document.getElementById(id);
const field = name => form.elements[name];

function status(msg, bad) { $('ai-status').textContent = msg; $('ai-status').className = 'note ' + (bad ? 'err' : ''); }
function showDetails() { $('details').hidden = false; }

// Put the AI's answer into the form and say how sure it is.
function fill(r) {
  for (const k of ['category', 'material', 'name', 'size', 'use', 'location',
                   'colour', 'condition', 'transparency', 'description']) field(k).value = r[k] || '';
  const pct = Math.round(r.confidence * 100);
  const check = Boolean(r.material && r.verify);    // under 95% sure: must tick the box to register
  status(r.material
    ? `AI thinks: ${r.name} (${r.material}, ${pct}% sure). ` +
      (r.unsure ? 'It is not sure. Please check the material.'
       : check ? 'Please check the details below, tick the box, then press Register.'
       : 'Check the details below, then press Register.')
    : 'The AI could not tell the material. Please fill it in.', r.unsure || !r.material);
  setVerify(check, pct);
  showDetails();
  sizeBox();
}

// Small scraps are only counted, so their size is not asked for (or saved).
function sizeBox() { $('size-box').hidden = field('category').value === 'small'; }
field('category').addEventListener('change', sizeBox);
sizeBox();

// The "I've checked it" box: shown (and required) only when the AI is not sure enough.
function setVerify(on, pct) {
  $('verify').hidden = !on;
  $('verify-ok').required = on;
  $('verify-ok').checked = false;
  if (on) $('verify-pct').textContent = pct + '%';
}

// Show the uploaded photo.
let previewUrl = null;
function showPreview(file) {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  $('preview').src = previewUrl; $('preview').hidden = $('preview-note').hidden = false;
}

$('photo').onchange = () => {                      // preview, then start the AI straight away
  if (!$('photo').files.length) return;
  showPreview($('photo').files[0]);
  if (AI_READY) identify();
};

// Send the photo (and weight, if filled in) to the AI. Runs when a photo is chosen.
let identifying = 0;                               // ignore answers for an earlier photo
async function identify() {
  const mine = ++identifying;
  const body = new FormData();
  body.append('photo', $('photo').files[0]);
  if ($('weight').value) body.append('weight_g', $('weight').value);
  status('Identifying… (up to about 30 seconds)');
  setVerify(false);                                 // a new photo gets a new answer
  try {
    const r = await (await fetch('/api/identify', { method: 'POST', body })).json();
    if (mine !== identifying) return;
    if (!r.ok) { status(r.error, true); return showDetails(); }
    fill(r);
  } catch (e) {
    if (mine !== identifying) return;
    status('Could not reach the server. Fill in the details by hand.', true); showDetails();
  }
}

if (AI_READY) $('manual').onclick = () => { setVerify(false); showDetails(); field('material').focus(); };

// ---- scale: read the weight only when the button is pressed ----
$('weigh').onclick = async () => {
  $('weigh').disabled = true;
  try {
    const r = await (await fetch('/api/station/weight')).json();
    if (!r.ok) return status(r.error, true);
    $('weight').value = r.weight_g;
    status(`Weight from the scale: ${r.weight_g} g.`);
  } catch (e) {
    status('Could not reach the server.', true);
  } finally { $('weigh').disabled = false; }
};

// While this page is open (and visible), keep the station from sorting the item being weighed.
function hold() { if (!document.hidden) fetch('/api/station/hold', { method: 'POST' }).catch(() => {}); }
hold();
setInterval(hold, 10000);
document.addEventListener('visibilitychange', hold);
addEventListener('pagehide', () => navigator.sendBeacon('/api/station/release'));
