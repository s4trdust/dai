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
  status(r.material
    ? `AI thinks: ${r.name} (${r.material}, ${pct}% sure). ` +
      (r.unsure ? 'It is not sure. Please check the material.' : 'Check the details below, then press Register.')
    : 'The AI could not tell the material. Please fill it in.', r.unsure || !r.material);
  showDetails();
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
  if (AI_READY) $('identify').click();
};

if (AI_READY) {
  $('manual').onclick = () => { showDetails(); field('material').focus(); };

  $('identify').onclick = async () => {
    if (!$('photo').files.length) return status('Choose or take a photo first.', true);
    const body = new FormData();
    body.append('photo', $('photo').files[0]);
    if ($('weight').value) body.append('weight_g', $('weight').value);
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
}

// ---- scale: read the weight only when the button is pressed ----
$('weigh').onclick = async () => {
  $('weigh').disabled = true;
  try {
    const r = await (await fetch('/api/station/weight')).json();
    if (!r.ok) return status(r.error, true);
    $('weight').value = r.weight_g;
    status(`Weight from the scale: ${r.weight_g} g.` +
           (AI_READY && $('photo').files.length ? ' Press "Identify with AI" again to use it.' : ''));
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
