// ACI Web Capture - background service worker (Manifest V3)
//
// When a page finishes loading, this reads the page's main text and POSTs it to
// the LOCAL ACI service (127.0.0.1). Nothing is ever sent anywhere else. The user
// controls everything from the popup: on/off, the ACI address, an optional API key,
// and a domain exclude-list. Broad "read all sites" access is requested only when
// the user explicitly turns capture on (see popup.js), never at install time.

const DEFAULTS = {
  enabled: false,                 // off until the user opts in (and grants site access)
  aci: "http://127.0.0.1:7077",
  apiKey: "",
  minLen: 250,
  excludes: ["mail.google.com", "web.whatsapp.com", "accounts.google.com",
             "login.microsoftonline.com"],
  count: 0,
  last: ""
};

const recent = new Map();          // url -> ts, in-memory throttle for this worker life

async function settings() {
  return await chrome.storage.local.get(DEFAULTS);
}

function hostOf(url) {
  try { return new URL(url).hostname; } catch (e) { return ""; }
}

function excluded(host, list) {
  return list.some(d => host === d || host.endsWith("." + d));
}

// Injected into the page; must be fully self-contained (no outer references).
function extractPage() {
  const root = document.querySelector("article") ||
               document.querySelector("main") || document.body;
  if (!root) return null;
  const parts = [];
  root.querySelectorAll("p,h1,h2,h3,h4,h5,li,td,blockquote,pre").forEach(el => {
    if (el.closest("nav,aside,footer,header")) return;
    const t = (el.innerText || "").trim();
    if (t.length > 15) parts.push(t);
  });
  let text = parts.join("\n");
  if (text.length < 250) text = (root.innerText || "").trim();
  return { url: location.href, title: document.title, text: text.slice(0, 200000) };
}

// Injected into the page: a small floating badge showing how many related
// memories ACI has about what you're looking at. Self-contained.
function injectBadge(count, consoleUrl) {
  try {
    const old = document.getElementById("aci-badge");
    if (old) old.remove();
    const d = document.createElement("div");
    d.id = "aci-badge";
    d.textContent = "✦ ACI · " + count + " related";
    d.title = "ACI has " + count + " related memories. Click to open the Console.";
    Object.assign(d.style, {
      position: "fixed", bottom: "16px", right: "16px", zIndex: 2147483647,
      background: "#1b1b2b", color: "#cfe3ff", font: "12px system-ui, sans-serif",
      padding: "6px 11px", borderRadius: "14px", boxShadow: "0 2px 10px rgba(0,0,0,.35)",
      cursor: "pointer", opacity: "0.94"
    });
    d.addEventListener("click", () => window.open(consoleUrl, "_blank"));
    document.body.appendChild(d);
    setTimeout(() => { d.style.transition = "opacity .6s"; d.style.opacity = "0";
                       setTimeout(() => d.remove(), 700); }, 6000);
  } catch (e) {}
}

async function capture(tabId, url) {
  const s = await settings();
  if (!s.enabled) return;
  if (!/^https?:\/\//.test(url)) return;
  const host = hostOf(url);
  if (!host || excluded(host, s.excludes)) return;

  const now = Date.now();
  if (recent.has(url) && now - recent.get(url) < 60000) return;  // 1/min per url
  recent.set(url, now);

  let page;
  try {
    const out = await chrome.scripting.executeScript({ target: { tabId }, func: extractPage });
    page = out && out[0] && out[0].result;
  } catch (e) { return; }                       // no host permission / restricted page
  if (!page || !page.text || page.text.length < s.minLen) return;

  try {
    const headers = { "Content-Type": "application/json" };
    if (s.apiKey) headers["X-API-Key"] = s.apiKey;
    const r = await fetch(s.aci + "/capture", {
      method: "POST", headers, body: JSON.stringify(page)
    });
    const j = await r.json();
    if (j && j.chunks > 0) {
      await chrome.storage.local.set({ count: (s.count || 0) + 1, last: page.title || page.url });
      chrome.action.setBadgeText({ text: String((s.count || 0) + 1) });
      chrome.action.setBadgeBackgroundColor({ color: "#2d6cdf" });
    }
  } catch (e) { /* ACI not running - silently skip */ }

  // in-page badge: how many related memories ACI already has about this page
  try {
    const headers = { "Content-Type": "application/json" };
    if (s.apiKey) headers["X-API-Key"] = s.apiKey;
    const rr = await fetch(s.aci + "/recall", {
      method: "POST", headers,
      body: JSON.stringify({ query: page.title || page.text.slice(0, 200), k: 5 })
    });
    const rj = await rr.json();
    const n = (rj.hits || []).length;
    if (n > 0) {
      await chrome.scripting.executeScript({ target: { tabId }, func: injectBadge,
                                             args: [n, s.aci + "/console"] });
    }
  } catch (e) { /* ACI not running */ }
}

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" && tab && tab.url) capture(tabId, tab.url);
});

// cross-AI memory bus: the "ground with ACI" button asks for relevant memory.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== "ground") return;
  (async () => {
    const s = await settings();
    try {
      const headers = { "Content-Type": "application/json" };
      if (s.apiKey) headers["X-API-Key"] = s.apiKey;
      const r = await fetch(s.aci + "/recall", {
        method: "POST", headers,
        body: JSON.stringify({ query: msg.text || "", k: 5 })
      });
      const j = await r.json();
      const ctx = (j.hits || [])
        .map(h => "- " + (h.summary || h.value || "").slice(0, 200)).join("\n");
      sendResponse({ context: ctx });
    } catch (e) {
      sendResponse({ context: "", error: String(e) });
    }
  })();
  return true;   // async response
});
