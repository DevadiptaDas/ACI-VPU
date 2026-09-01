# Use ACI with all your AIs — one shared memory

ACI gives every AI you use the **same** private, on-device memory. Connect them once and
they share what they know, hand off to each other, and stay factually in sync — with
nothing leaving your machine. **Free tier: up to 3 connected AIs** (unlimited on Pro).

## 1. Start ACI (once)
```bash
pip install "aci-vpu[full]"     # semantic memory + cost engine
py quickstart.py                # runs the local service — keep it running
```

## 2. Connect Claude Code / Claude Desktop / Cursor  (MCP — the smooth path)
```bash
claude mcp add aci --env ACI_URL=http://127.0.0.1:7077 -- py "<path>/mcp_aci.py"
```
Restart the AI host. It now **recalls from and writes to your ACI automatically, every
session** — no per-message steps. (Cursor: add the same server in its MCP settings.)
Each AI announces itself, e.g. *"✦ via ACI — recalled 3 of your notes."*

## 3. Connect ChatGPT / Claude.ai in the browser
1. `chrome://extensions` → Developer mode → **Load unpacked** → `clients/browser-extension`
2. On the AI's page, click **"✦ ground with ACI"** to pull your memory into the prompt.
   *(Note: this sends your recalled context to that AI's cloud on click — the private path
   is MCP + a local model.)*

## 4. Connect a local model  (the cost engine)
Install the UQRT-MCA NLP brain — it answers easy questions with a **free local model** and
only escalates hard ones to a paid model, so your bill drops on repetitive work.

## What you get
- Ask **Claude** something, switch to **GPT** — GPT already knows it. One memory across all of them.
- Every AI's answer is grounded in your **current, truth-checked** facts (not stale ones).
- Every question answered from memory is a **model call you didn't pay for**.

## Free vs. paid
| | Free | Pro |
|---|---|---|
| Connected AIs | up to **3** | **unlimited** |
| How | default | `set ACI_LICENSE=<your-key>` before starting ACI |

The user's own device (Console, file-watcher, SDK) is **never** counted against the cap —
only self-identifying AI connections (Claude, GPT, Cursor, …) do.
