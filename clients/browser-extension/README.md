# ACI Web Capture (browser extension)

Auto-captures the pages you actually read into your **local** ACI memory, so ACI
knows what you've seen on the web — searchable by meaning, alongside your files.
**Everything stays on your device:** the extension only talks to your local ACI
service (`127.0.0.1:7077`). Nothing is sent to any cloud.

## Install (Chrome / Edge / Brave / Arc — any Chromium browser)
1. Start ACI: `py quickstart.py` (in the `ACI- VPU` folder).
2. Open `chrome://extensions` (or `edge://extensions`).
3. Turn on **Developer mode** (top-right).
4. Click **Load unpacked** → select this `browser-extension` folder.
5. Click the ACI puzzle-piece icon → flip **Capture browsing** on.
   - The browser asks for permission to read the sites you visit. This is requested
     **only at opt-in**, never at install — that grant is what lets ACI see pages.

That's it. Now browse normally; pages flow into ACI on their own. The badge shows
how many pages have been captured; the popup shows live ACI connection + count.

## What it captures
- The **main readable text** of each page you load (article/main content; nav,
  ads, footers stripped), with the title and URL.
- Revisiting an unchanged page is a **no-op** (content-fingerprinted server-side);
  a changed page cleanly supersedes its old version — same incremental logic as files.

## Your controls (in the popup)
- **On/off** toggle (off by default).
- **ACI address** + optional **API key** (if you run ACI with `ACI_API_KEY`).
- **Never capture these sites** — domain exclude-list. Ships with mail/auth domains
  (`mail.google.com`, `accounts.google.com`, …) pre-excluded; add your bank etc.
- **Reset count**, and **Open ACI Console** to search/inspect/forget what's stored.
- HTTP/HTTPS pages only; `http://`-internal and `chrome://` pages are never touched.

## In-page badge
On pages you read (when capture is on), a small floating **"✦ ACI · N related"** badge
appears bottom-right, showing how many related memories ACI already has about what
you're looking at. Click it to open the Console; it fades after a few seconds. The
count comes from a local `/recall` the background worker runs (the page itself never
talks to ACI directly).

## How it works
`background.js` listens for a tab finishing load → injects a small extractor →
POSTs `{url, title, text}` to `POST /capture` on your local ACI. ACI chunks,
embeds, extracts entities, dedups, and stores it as `source_type="WEB"`. To remove
a page: ACI Console → find it → forget (or `forget_by_source` with the URL).
