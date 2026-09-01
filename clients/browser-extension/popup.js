// ACI Web Capture - popup controller
const DEFAULTS = {
  enabled: false, aci: "http://127.0.0.1:7077", apiKey: "", minLen: 250,
  excludes: ["mail.google.com", "web.whatsapp.com", "accounts.google.com",
             "login.microsoftonline.com"],
  count: 0, last: ""
};
const ALL_SITES = { origins: ["http://*/*", "https://*/*"] };
const $ = id => document.getElementById(id);

async function load() {
  const s = await chrome.storage.local.get(DEFAULTS);
  $("enabled").checked = s.enabled;
  $("aci").value = s.aci;
  $("apiKey").value = s.apiKey;
  $("excludes").value = (s.excludes || []).join("\n");
  $("count").textContent = s.count || 0;
  $("last").textContent = s.last ? "last: " + s.last : "";
  checkConn(s);
}

async function checkConn(s) {
  try {
    const r = await fetch(s.aci + "/health", { headers: s.apiKey ? { "X-API-Key": s.apiKey } : {} });
    const j = await r.json();
    $("dot").className = "dot ok";
    $("conn").textContent = "ACI connected · " + (j.monads ?? "?") + " monads";
  } catch (e) {
    $("dot").className = "dot bad";
    $("conn").textContent = "ACI not running (start it: py quickstart.py)";
  }
}

async function save(patch) {
  await chrome.storage.local.set(patch);
}

$("enabled").addEventListener("change", async (e) => {
  if (e.target.checked) {
    // Ask for read access to all sites ONLY now, on explicit opt-in.
    const granted = await chrome.permissions.request(ALL_SITES);
    if (!granted) { e.target.checked = false; return; }
  }
  await save({ enabled: e.target.checked });
});

$("aci").addEventListener("change", e => { save({ aci: e.target.value.trim().replace(/\/$/, "") }); load(); });
$("apiKey").addEventListener("change", e => save({ apiKey: e.target.value.trim() }));
$("excludes").addEventListener("change", e =>
  save({ excludes: e.target.value.split("\n").map(x => x.trim()).filter(Boolean) }));

$("reset").addEventListener("click", async () => {
  await save({ count: 0, last: "" });
  chrome.action.setBadgeText({ text: "" });
  load();
});

$("console").addEventListener("click", async () => {
  const s = await chrome.storage.local.get(DEFAULTS);
  chrome.tabs.create({ url: s.aci + "/console" });
});

load();
