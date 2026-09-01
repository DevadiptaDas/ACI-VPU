// ACI cross-AI memory bus (#2) - browser side.
// On AI chat sites (ChatGPT / Claude.ai / Gemini), a "✦ ground with ACI" button
// pulls relevant memory from your LOCAL ACI and inserts it above your prompt, so the
// web AI answers grounded in the SAME memory your MCP-connected AIs use. Best-effort
// per-site input handling; explicit click (your recalled context goes to that AI's
// cloud only when you choose to ground a message).
(async function () {
  let s;
  try { s = await chrome.storage.local.get({ enabled: false }); } catch (e) { return; }
  if (!s.enabled) return;
  if (document.getElementById("aci-ground-btn")) return;

  function findInput() {
    return document.querySelector("#prompt-textarea")
        || document.querySelector('div[contenteditable="true"]')
        || document.querySelector(".ql-editor")
        || document.querySelector("textarea");
  }

  function readText(el) {
    return (el.value !== undefined ? el.value : el.innerText) || "";
  }

  function insertText(el, text) {
    el.focus();
    if (el.value !== undefined) {                       // <textarea>
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value").set;
      setter.call(el, text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    } else {                                            // contenteditable / rich editor
      el.innerText = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  const btn = document.createElement("button");
  btn.id = "aci-ground-btn";
  btn.textContent = "✦ ground with ACI";
  Object.assign(btn.style, {
    position: "fixed", bottom: "16px", left: "16px", zIndex: 2147483647,
    background: "#1b1b2b", color: "#cfe3ff", font: "12px system-ui, sans-serif",
    border: "none", padding: "7px 12px", borderRadius: "14px",
    boxShadow: "0 2px 10px rgba(0,0,0,.35)", cursor: "pointer", opacity: "0.94"
  });
  btn.addEventListener("click", async () => {
    const el = findInput();
    if (!el) { btn.textContent = "✦ no input found"; return; }
    const cur = readText(el).trim();
    btn.textContent = "…";
    let resp;
    try { resp = await chrome.runtime.sendMessage({ type: "ground", text: cur }); }
    catch (e) { resp = null; }
    const ctx = resp && resp.context;
    if (!ctx) {
      btn.textContent = "✦ no ACI context";
      setTimeout(() => (btn.textContent = "✦ ground with ACI"), 2000);
      return;
    }
    insertText(el, "Context from my ACI memory (use if relevant):\n" + ctx + "\n\n" + cur);
    btn.textContent = "✦ grounded";
    setTimeout(() => (btn.textContent = "✦ ground with ACI"), 2000);
  });
  document.body.appendChild(btn);
})();
