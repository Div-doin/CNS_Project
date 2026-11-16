"use strict";

const $ = id => document.getElementById(id);
const state = {hide: null, extract: null, output: null, busy: false,
  sequence: {hide: 0, extract: 0}, active: "hide"};
const utf8 = new TextEncoder();
const format = n => n.toLocaleString();

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

function updateControls() {
  const length = utf8.encode($("message").value).length;
  const limit = state.hide?.info.capacity_bytes ?? 0;
  $("byte-count").textContent = `${format(length)} UTF-8 bytes`;
  $("capacity-text").textContent = state.hide ? `${format(limit)} bytes available` : "Select an image to see capacity";
  $("byte-count").classList.toggle("over-capacity", !!state.hide && length > limit);
  $("capacity-meter").value = limit ? Math.min(100, 100 * length / limit) : 0;
  document.querySelectorAll(".action, .tab").forEach(button => button.disabled = state.busy);
  $("hide-file").disabled = state.busy;
  $("extract-file").disabled = state.busy;
  $("message").disabled = state.busy;
  $("encode").disabled = state.busy || !state.hide || !length || length > limit;
  $("decode").disabled = state.busy || !state.extract;
  $("encode").textContent = state.busy && state.active === "hide" ? "Working…" : "Hide message and create PNG ↗";
  $("decode").textContent = state.busy && state.active === "extract" ? "Working…" : "Extract hidden message ↗";
}

async function busy(action) {
  if (state.busy) return;
  state.busy = true;
  notice();
  updateControls();
  try { await action(); }
  catch (error) { notice(error.message || "Something went wrong. Please try again."); }
  finally { state.busy = false; updateControls(); }
}

async function api(action, body) {
  let response;
  try {
    response = await fetch(`/api/${action}`, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  } catch (_) { throw new Error("Cannot reach the local app. Keep its Python window open and try again."); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The image could not be processed.");
  return result;
}

async function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("The selected image could not be read."));
    reader.readAsDataURL(file);
  });
}

function clearResult(mode) {
  if (mode === "hide") { state.output = null; $("hide-result").hidden = true; }
  else { $("extract-result").hidden = true; $("extract-empty").hidden = false; $("recovered").value = ""; }
}

function renderSelection(mode) {
  const item = state[mode];
  $(`${mode}-upload`).hidden = !!item;
  $(`${mode}-preview`).hidden = !item;
  if (item) {
    $(`${mode}-image`).src = `data:image/png;base64,${item.image}`;
    $(`${mode}-name`).textContent = item.name;
    $(`${mode}-info`).textContent = `${item.info.width} × ${item.info.height} pixels · ${item.info.mode} · ${format(item.info.capacity_bytes)} message bytes capacity`;
  } else {
    $(`${mode}-image`).removeAttribute("src");
    $(`${mode}-info`).textContent = mode === "hide"
      ? "The original file stays unchanged. Your output is a separate PNG."
      : "Use the original encoded PNG. Resizing or JPEG conversion can damage its hidden text.";
  }
}

async function selectFile(mode, file) {
  const sequence = ++state.sequence[mode];
  clearResult(mode);
  state[mode] = null;
  renderSelection(mode);
  updateControls();
  if (!file) return;
  if (file.size > 12 * 1024 * 1024) throw new Error("Choose a PNG no larger than 12 MiB.");
  const image = await fileBase64(file);
  const info = await api("inspect", {image});
  if (sequence !== state.sequence[mode]) return;
  state[mode] = {image, name: file.name, info};
  renderSelection(mode);
  updateControls();
}

function activate(mode) {
  state.active = mode;
  notice();
  for (const name of ["hide", "extract"]) {
    $(`${name}-tab`).classList.toggle("active", mode === name);
    $(`${name}-tab`).setAttribute("aria-selected", String(mode === name));
    $(`${name}-tab`).tabIndex = mode === name ? 0 : -1;
    $(`${name}-panel`).hidden = mode !== name;
  }
  updateControls();
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function imageBlob(base64) {
  const bytes = Uint8Array.from(atob(base64), char => char.charCodeAt(0));
  return new Blob([bytes], {type: "image/png"});
}

function showEncoding(result) {
  state.output = result;
  const m = result.metrics;
  $("metric-bytes").textContent = `${format(m.message_bytes)} bytes`;
  $("metric-changed").textContent = `${format(m.changed_channels)} (${m.changed_percent}%)`;
  $("metric-psnr").textContent = m.psnr_db === null ? "∞ dB" : `${m.psnr_db} dB`;
  $("metric-time").textContent = `${m.encode_ms} ms`;
  $("compare-original").src = `data:image/png;base64,${state.hide.image}`;
  $("compare-encoded").src = `data:image/png;base64,${result.image}`;
  $("bit-rows").replaceChildren();
  for (const sample of m.samples) {
    const row = document.createElement("tr");
    const values = [sample.pixel, sample.channel,
      `${sample.before.toString(2).padStart(8, "0")} (${sample.before})`, sample.bit,
      `${sample.after.toString(2).padStart(8, "0")} (${sample.after})`];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 2 || index === 4) cell.className = "code";
      row.appendChild(cell);
    });
    $("bit-rows").appendChild(row);
  }
  $("hide-result").hidden = false;
}

async function extract() {
  clearResult("extract");
  const result = await api("extract", {image: state.extract.image});
  $("recovered").value = result.message;
  $("decode-stats").textContent = `${format(result.message_bytes)} UTF-8 bytes · ${result.message_characters} Unicode code points · ${result.decode_ms} ms · CRC32 ${result.checksum}`;
  $("extract-empty").hidden = true;
  $("extract-result").hidden = false;
}

for (const mode of ["hide", "extract"]) {
  $(`${mode}-tab`).addEventListener("click", () => activate(mode));
  $(`${mode}-tab`).addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) && !state.busy) {
      event.preventDefault();
      const next = event.key === "Home" ? "hide" : event.key === "End" ? "extract" : mode === "hide" ? "extract" : "hide";
      activate(next); $(`${next}-tab`).focus();
    }
  });
  $(`${mode}-change`).addEventListener("click", () => $(`${mode}-file`).click());
  $(`${mode}-file`).addEventListener("change", () => {
    const file = $(`${mode}-file`).files[0];
    busy(() => selectFile(mode, file));
    $(`${mode}-file`).value = "";
  });
}
$("message").addEventListener("input", () => { clearResult("hide"); notice(); updateControls(); });
$("demo").addEventListener("click", () => busy(async () => {
  const response = await fetch("/api/demo");
  if (!response.ok) throw new Error("The sample image could not be loaded.");
  await selectFile("hide", new File([await response.blob()], "sample_cover.png", {type: "image/png"}));
  if (!$("message").value) $("message").value = "Meet me at the library at 4 PM.\nCNS mini project: a message hidden in pixels.";
}));
$("encode").addEventListener("click", () => busy(async () => {
  clearResult("hide");
  showEncoding(await api("hide", {image: state.hide.image, message: $("message").value}));
}));
$("decode").addEventListener("click", () => busy(extract));
$("download-png").addEventListener("click", () => {
  if (!state.output) return;
  const stem = state.hide.name.replace(/\.png$/i, "");
  download(imageBlob(state.output.image), `${stem}_encoded.png`);
});
$("download-text").addEventListener("click", () => download(new Blob([$("recovered").value], {type: "text/plain;charset=utf-8"}), "recovered_message.txt"));
$("use-output").addEventListener("click", () => busy(async () => {
  const output = state.output;
  activate("extract");
  await selectFile("extract", new File([imageBlob(output.image)], "encoded_message.png", {type: "image/png"}));
  await extract();
}));
updateControls();
