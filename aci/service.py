"""
ACI service (Phase 4) - the productized universal cognition service.

Open HTTP/JSON interface any client/language connects to. Adds, over Phase 0-3:
  - admin/privacy endpoints:  GET /monads,  POST /forget  (right-to-be-forgotten)
  - GET /openapi.json         machine-readable API spec
  - GET /console              built-in admin/privacy dashboard (HTML)

Endpoints:
  GET  /health  /compress  /monads?limit=  /openapi.json  /console
  POST /monadise /recall /validate /relate /route /forget

Env: ACI_PORT, ACI_DB, ACI_OBSERVER, ACI_EMBEDDER, ACI_API_KEY
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci import ACI, Observer, __version__ as ACI_VERSION  # noqa: E402
from aci.ingest import ingest_directory, ingest_web  # noqa: E402
from aci import device as _device  # noqa: E402
from aci import archive as _archive  # noqa: E402
from aci import observe as _observe  # noqa: E402
from aci import mail as _mail  # noqa: E402
from aci import redact as _redact  # noqa: E402
from aci import logsetup as _logsetup  # noqa: E402
from aci import activity as _activity_mod  # noqa: E402

_log = _logsetup.logging.getLogger("aci")
_activity = _activity_mod.ActivityLog()

# Files /open may hand to os.startfile — an ALLOWLIST of inert document/media types.
# startfile RUNS whatever the shell associates with the extension; allowlisting (with
# a trailing dot/space trim, since Windows trims "x.exe." to "x.exe") means an
# unknown/executable/blank extension is refused, not run. Directories are allowed.
_SAFE_OPEN_EXT = {".pdf", ".txt", ".md", ".rtf", ".csv", ".tsv", ".log", ".json",
                  ".xml", ".yaml", ".yml", ".ini", ".cfg", ".epub",
                  ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".odt", ".ods", ".odp",
                  ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff",
                  ".ico", ".heic", ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac",
                  ".opus", ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".zip"}


def _safe_to_open(path: str) -> bool:
    base = os.path.basename(path or "").rstrip(" .")
    return os.path.splitext(base)[1].lower() in _SAFE_OPEN_EXT


MAX_BODY = 5 * 1024 * 1024
REQUIRED = {
    "/monadise": ["content"], "/recall": ["query"], "/validate": ["statement"],
    "/verify": ["id"],
    "/relate": ["source_id", "target_id"], "/route": ["query"], "/forget": ["id"],
    "/forget_by_source": ["path"], "/supersede": ["old_id"],
    "/assert_fact": ["content", "fact_key"],
    "/ingest": ["path"],
    "/watch": ["path"],
    "/unwatch": ["path"],
    "/capture": ["url", "text"],
    "/pause": [],
    "/consent": ["scope"],
    "/scan_dupes": ["path"],
    "/clean": ["paths"],
    "/archive": ["path"],
    "/restore": ["path"],
    "/delete_original": ["path"],
    "/forget_archive": ["path"],
    "/observe": [],
    "/ocr_screen": [],
    "/ingest_mail": ["host", "user", "password"],
    "/wipe": [],
    "/backup": ["path"],
    "/compact": [],
    "/recall_images": ["query"],
    "/save_skill": ["name", "intent", "body"],
    "/find_skills": ["intent"],
    "/skill_outcome": ["skill_id"],
    "/log_event": ["action"],
    "/patterns": [],
    "/suggest": [],
    "/proactive_feedback": ["action", "accepted"],
}

_aci = None
_lock = threading.Lock()
_CONN_GATE = None


def _connection_gate():
    """Lazy free-tier AI-connection gate (soft 3-AI cap; a Pro/Team license lifts it).
    Only self-identifying AIs (requests carrying `agent`) are counted."""
    global _CONN_GATE
    if _CONN_GATE is None:
        from aci import license as _lic
        db = os.environ.get("ACI_DB", "aci_data.db")
        base = os.path.dirname(os.path.abspath(db)) or "."
        gpath = os.path.join(base, "aci_connections.json")
        _CONN_GATE = (_lic.ConnectionGate(_lic.resolve_tier(), _lic.load_known(gpath)), gpath)
    return _CONN_GATE
_api_key = ""
_bound_host = "127.0.0.1"        # set in main(); the CSRF guard only enforces on loopback binds
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")

WATCH_INTERVAL = int(os.environ.get("ACI_WATCH_INTERVAL", "30"))
_watch_stop = threading.Event()
_srv = None
_last_sync = {}


def _watch_loop():
    """Autonomy: periodically re-sync every watched folder (incremental, so it
    only does work when files actually change). Runs in a background thread."""
    while not _watch_stop.wait(WATCH_INTERVAL):
        try:
            with _lock:
                folders = _aci.store.all_watched()
            for folder in folders:
                if os.path.isdir(folder) and _aci.store.is_allowed("FILE", folder):
                    # embeds lock-free; only brief per-file writes hold _lock, so
                    # foreground recall/validate stay responsive during indexing.
                    st = ingest_directory(_aci, folder, lock=_lock)
                    _last_sync[folder] = time.time()
                    if st.get("new") or st.get("updated"):
                        _activity.record("capture", f"auto-synced {os.path.basename(folder)}: "
                                         f"{st.get('new', 0)} new, {st.get('updated', 0)} updated")
        except Exception:
            _log.exception("watch loop error")


OBSERVE_INTERVAL = int(os.environ.get("ACI_OBSERVE_INTERVAL", "5"))
_obs_last = {"window": None, "clip": None}


def _observe_loop():
    """Phase D: when observation is ON (and not paused), periodically capture the
    active window and (only if explicitly opted-in) the clipboard. Secret-redacted:
    capture is suppressed while a password manager / login screen is focused, bare
    credentials are skipped, and any secret shapes in captured text are masked.
    Dedupes consecutive identical captures. OFF by default."""
    from aci import observe
    while not _watch_stop.wait(OBSERVE_INTERVAL):
        try:
            if _aci.store.get_meta("observe") != "1" or _aci.store.is_paused():
                continue
            w = observe.active_window()
            sensitive = _redact.is_sensitive_window(
                w.get("title") if w else "", w.get("process") if w else "")
            if sensitive:
                continue                                  # don't capture on credential screens
            if _aci.store.is_allowed("WINDOW") and w and w.get("title"):
                key = f"{w['process']}|{w['title']}"
                if key != _obs_last["window"]:
                    _obs_last["window"] = key
                    title, _ = _redact.redact_text(w["title"])
                    with _lock:
                        _aci.monadise(f"{w['process']}: {title}", source_type="WINDOW",
                                      metadata={"kind": "window", "process": w["process"],
                                                "title": title})
                    _activity.record("capture", f"saw active window: {title[:50]}")
            if _aci.store.consent_get("CLIPBOARD") is True:     # explicit opt-in only
                t = observe.read_clipboard_text()
                if t and len(t.strip()) > 3 and t != _obs_last["clip"]:
                    _obs_last["clip"] = t
                    if not _redact.is_probably_secret(t):       # skip bare credentials
                        red, _n = _redact.redact_text(t.strip()[:4000])
                        with _lock:
                            _aci.monadise(red, source_type="CLIPBOARD",
                                          metadata={"kind": "clipboard"})
                        _activity.record("capture", "captured clipboard text")
        except Exception:
            _log.exception("observe loop error")


def monad_view(m) -> dict:
    return {"id": m.id, "source_type": m.source_type, "summary": m.summary,
            "value": m.value, "truth_value": round(m.truth_value, 4),
            "entropy": round(m.entropy, 4), "keywords": m.keywords,
            "metadata": m.metadata, "observer_id": m.observer_id, "timestamp": m.timestamp}


def build_observer(d):
    o = d.get("observer")
    if not o:
        return None
    return Observer(id=o.get("id", "observer-0"), trust=o.get("trust") or {},
                    visible=set(o["visible"]) if o.get("visible") else None)


OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "ACI - Artificial Cognition Infrastructure", "version": ACI_VERSION},
    "paths": {
        "/health": {"get": {"summary": "Service health + monad count"}},
        "/compress": {"get": {"summary": "Storage/compression stats"}},
        "/monads": {"get": {"summary": "List stored monads (admin)",
                            "parameters": [{"name": "limit", "in": "query",
                                            "schema": {"type": "integer"}}]}},
        "/monadise": {"post": {"summary": "Turn raw info into a monad (+dedup+supersession)"}},
        "/recall": {"post": {"summary": "Retrieve by meaning (observer-relative)"}},
        "/validate": {"post": {"summary": "Check a statement: contradiction+confidence+trace"}},
        "/relate": {"post": {"summary": "Link two monads in the meaning field"}},
        "/route": {"post": {"summary": "Local-vs-cloud routing decision"}},
        "/forget": {"post": {"summary": "Delete a monad (right to be forgotten)"}},
    },
}

CONSOLE_HTML = """<!doctype html><html><head><meta charset=utf-8>
<title>ACI Console</title><style>
body{font:14px system-ui,sans-serif;margin:24px;max-width:900px;color:#111}
h1{font-size:20px}.row{margin:8px 0}input,button{font:14px inherit;padding:6px}
input[type=text]{width:320px}table{border-collapse:collapse;width:100%;margin-top:12px}
td,th{border:1px solid #ddd;padding:6px;text-align:left;font-size:13px}
.muted{color:#777}.tag{background:#eef;padding:1px 6px;border-radius:4px;font-size:12px}
button{cursor:pointer}#stats{background:#f6f6f6;padding:10px;border-radius:6px}
</style></head><body>
<h1>ACI Console <span class=muted id=ver></span></h1>
<div class=row>API key (if set): <input id=key type=text placeholder="X-API-Key">
<button onclick=refresh()>Refresh</button></div>
<div id=stats class=row></div>
<div id=activitybox class=row style="background:#eafaf0;border-radius:8px;padding:8px 11px">
<b>ACI activity</b> <span class=muted>- what ACI is doing for you, live</span>
<div id=feed class=muted style="margin-top:6px;max-height:150px;overflow:auto;font-size:12px;line-height:1.6"></div></div>
<div class=row>Add fact: <input id=fact type=text placeholder="e.g. The project deadline is April 2.">
<button onclick=addFact()>Add</button></div>
<div class=row>Ingest folder: <input id=folder type=text placeholder="C:\\Users\\you\\Documents" style="width:360px">
<button onclick=ingestFolder()>Ingest</button> <span id=ingstat class=muted></span></div>
<div class=row>Auto-watch folder: <input id=wfolder type=text placeholder="folder ACI keeps in sync by itself" style="width:330px">
<button onclick=watchFolder()>Watch</button></div>
<div id=watching class=row></div>
<div class=row id=privacy style="background:#f6f6f9;border-radius:8px;padding:8px 11px">
<b>Privacy &amp; control</b> &nbsp; <span id=encbadge class=tag></span>
<label style="margin-left:10px"><input type=checkbox id=pausebox onchange=togglePause()> <b>Pause all capture</b></label>
<div id=consent class=muted style="margin-top:6px"></div></div>
<div class=row id=deviceopt style="background:#eef4ff;border-radius:8px;padding:8px 11px">
<b>Device optimization (USP-2)</b> <button onclick=loadDevice()>Refresh health</button>
<div id=devhealth class=muted style="margin-top:6px">click "Refresh health"</div>
<div style="margin-top:8px">Scan folder for duplicates:
<input id=dupfolder type=text placeholder="C:\\Users\\you\\Downloads" style="width:300px">
<button onclick=scanDupes()>Scan</button> <span id=dupstat class=muted></span></div>
<div id=dupresult style="margin-top:6px"></div></div>
<div class=row id=observe style="background:#f0eaff;border-radius:8px;padding:8px 11px">
<b>Activity observation (Phase D)</b> <span class=muted>device watching itself, locally - OFF by default</span>
<label style="margin-left:10px"><input type=checkbox id=obsbox onchange=toggleObserve()> observe active window</label>
<span class=muted id=obsstat></span>
<div style="margin-top:6px"><label><input type=checkbox id=clipbox onchange=toggleClip()> also capture <b>clipboard</b> (sensitive - explicit opt-in)</label></div>
<div style="margin-top:6px"><button onclick=focusedText()>read focused text (D2)</button>
<button onclick=ocrScreen()>OCR screen (D3)</button> <span class=muted id=obsout></span></div>
<div style="margin-top:6px">Email (IMAP, D4):
<input id=mhost type=text placeholder="imap.gmail.com" style="width:130px">
<input id=muser type=text placeholder="you@mail.com" style="width:150px">
<input id=mpass type=password placeholder="app password" style="width:120px">
<button onclick=ingestMail()>Ingest mail</button> <span class=muted id=mailstat></span></div></div>
<div class=row>Check statement: <input id=stmt type=text placeholder="a claim to validate against memory" style="width:360px">
<button onclick=checkStmt()>Check</button></div>
<div id=vout class=row></div>
<div class=row>Recall: <input id=q type=text placeholder="search by meaning">
<input id=obs type=text placeholder="observer (optional)" style="width:140px">
<button onclick=recall()>Search</button></div>
<div id=out></div>
<div class=row>Photo search: <input id=pq type=text placeholder="describe an image, e.g. sunset over water" style="width:320px">
<button onclick=photoSearch()>Find photos</button> <span id=pstat class=muted></span></div>
<div id=photos></div>
<div class=row id=memcomp style="background:#fff3e6;border-radius:8px;padding:8px 11px">
<b>Memory compressor</b> <span class=muted>(monadise + losslessly compress; delete originals, restore byte-exact)</span>
<div style="margin-top:6px">Archive folder: <input id=arcfolder type=text placeholder="folder to compress + index" style="width:320px">
<button onclick=archiveFolder()>Archive</button> <span id=arcstat class=muted></span></div>
<div id=arclist style="margin-top:6px"></div></div>
<div class=row>Route (local vs cloud): <input id=rq type=text placeholder="a task/query" style="width:280px">
<button onclick=routeQ()>Route</button> <span id=rout class=muted></span>
&nbsp;|&nbsp; <button onclick=loadGraph()>Show knowledge graph</button> <span id=graphout class=muted></span></div>
<h3>Stored monads <span class=muted>(privacy view)</span></h3>
<div id=monads></div>
<script>
const H=()=>{const k=document.getElementById('key').value;return k?{'X-API-Key':k}:{}}
async function j(p,o={}){const r=await fetch(p,{...o,headers:{'Content-Type':'application/json',...H(),...(o.headers||{})}});return r.json()}
async function refresh(){
 const h=await j('/health');document.getElementById('ver').textContent='v'+(h.version||'');
 const c=await j('/compress');
 document.getElementById('stats').innerHTML=
  `monads: <b>${h.monads}</b> &nbsp; embedder: <span class=tag>${h.embedder}</span> &nbsp;`+
  `stored: ${c.stored_bytes} B &nbsp; dups merged: ${c.duplicates_merged} &nbsp; ratio: ${c.compression_ratio}x`;
 listMonads();
 loadWatched();
 loadPolicy();
 loadArchives();
 loadActivity();
}
async function loadActivity(){const d=await j('/activity?since=0');
 const evs=(d.events||[]).slice(-15).reverse();
 const tag={recall:'#2d6cdf',ground:'#1ea672',remember:'#7a4cdf',capture:'#c07b1a',optimize:'#1a9c8a'};
 document.getElementById('feed').innerHTML = evs.length
  ? evs.map(e=>`<span style="color:${tag[e.kind]||'#666'};font-weight:600">[${e.kind}]</span> ${e.summary}`).join('<br>')
  : '<span class=muted>no activity yet - recall/ingest/check a statement and it shows up here</span>';}
async function loadPolicy(){const p=await j('/policy');
 document.getElementById('encbadge').textContent=p.encrypted?('encrypted · '+p.encryption):'not encrypted';
 document.getElementById('encbadge').style.background=p.encrypted?'#d8f3e3':'#f3d8d8';
 document.getElementById('pausebox').checked=p.paused;
 const cmap={};(p.consent||[]).forEach(c=>cmap[c.scope]=c.allowed);
 let h='capture by source: ';
 (p.kinds||[]).forEach(k=>{const on=(cmap[k]!==false);
  h+=`<label style="margin-right:12px"><input type=checkbox ${on?'checked':''} onchange="setConsent('${k}',this.checked)"> ${k}</label>`;});
 document.getElementById('consent').innerHTML=h;
 const ob=document.getElementById('obsbox');if(ob)ob.checked=!!p.observing;
 const cb=document.getElementById('clipbox');if(cb)cb.checked=(cmap['CLIPBOARD']===true);
 const os=document.getElementById('obsstat');if(os)os.textContent=p.observing?'· observing':'· off';}
async function togglePause(){await j('/pause',{method:'POST',body:JSON.stringify({paused:document.getElementById('pausebox').checked})});loadPolicy();}
async function setConsent(scope,allowed){await j('/consent',{method:'POST',body:JSON.stringify({scope,allowed})});loadPolicy();}
async function listMonads(){
 const d=await j('/monads?limit=50');
 let t='<table><tr><th>source</th><th>summary</th><th>ψ</th><th>S</th><th></th></tr>';
 for(const m of d.monads){t+=`<tr><td><span class=tag>${m.source_type}</span></td>`+
  `<td>${(m.summary||'').slice(0,80)}</td><td>${m.truth_value}</td><td>${m.entropy}</td>`+
  `<td><button onclick="forget('${m.id}')">forget</button></td></tr>`}
 document.getElementById('monads').innerHTML=t+'</table>';
}
async function recall(){
 const q=document.getElementById('q').value;
 const o=document.getElementById('obs').value;
 const d=await j('/recall',{method:'POST',body:JSON.stringify({query:q,k:5,observer:o?{id:o}:null})});
 let t='<table><tr><th>score</th><th>source</th><th>match (cross-app)</th></tr>';
 for(const h of d.hits){const o=(h.metadata&&(h.metadata.path||h.metadata.title))||'';
  t+=`<tr><td>${h.score}</td><td><span class=tag>${h.source_type}</span></td>`+
   `<td>${(h.summary||'').slice(0,90)}${o?('<br><span class=muted>'+o+'</span>'):''}</td></tr>`}
 document.getElementById('out').innerHTML=t+'</table>';
}
async function addFact(){const v=document.getElementById('fact').value;if(!v)return;
 await j('/monadise',{method:'POST',body:JSON.stringify({content:v,source_type:'CONSOLE',truth_value:2.0})});
 document.getElementById('fact').value='';refresh()}
async function ingestFolder(){const p=document.getElementById('folder').value;if(!p)return;
 document.getElementById('ingstat').textContent='ingesting...';
 const r=await j('/ingest',{method:'POST',body:JSON.stringify({path:p})});
 document.getElementById('ingstat').textContent=`+${r.new} new, ${r.updated} updated, ${r.skipped} skipped (${r.chunks} chunks)`;
 refresh()}
let WATCHED=[];
async function watchFolder(){const p=document.getElementById('wfolder').value;if(!p)return;
 await j('/watch',{method:'POST',body:JSON.stringify({path:p})});document.getElementById('wfolder').value='';refresh()}
async function unwatchFolder(i){await j('/unwatch',{method:'POST',body:JSON.stringify({path:WATCHED[i]})});refresh()}
async function loadWatched(){const d=await j('/watched');WATCHED=d.watched;const ls=d.last_sync||{};
 let h=WATCHED.length?`<b>Auto-watching</b> (re-syncs every ${d.interval_s}s): `:'<span class=muted>not auto-watching any folder yet - add one above to make it self-feeding</span>';
 WATCHED.forEach((p,i)=>{const t=(ls[p]!=null)?` &middot; synced ${ls[p]}s ago`:' &middot; pending';h+=`<span class=tag>${p}${t} <a href="#" onclick="unwatchFolder(${i});return false">x</a></span> `});
 document.getElementById('watching').innerHTML=h}
async function checkStmt(){const s=document.getElementById('stmt').value;if(!s)return;
 const r=await j('/validate',{method:'POST',body:JSON.stringify({statement:s})});
 let h=`<b>${r.is_consistent?'CONSISTENT':'CONTRADICTION FOUND'}</b> &nbsp;confidence ${r.confidence}`;
 if(r.contradictions&&r.contradictions.length){h+='<ul>';for(const c of r.contradictions){h+='<li>'+(c.explanation||JSON.stringify(c))+'</li>'}h+='</ul>'}
 document.getElementById('vout').innerHTML=h}
async function forget(id){await j('/forget',{method:'POST',body:JSON.stringify({id})});refresh()}
async function photoSearch(){const q=document.getElementById('pq').value;if(!q)return;
 document.getElementById('pstat').textContent='searching...';
 const d=await j('/recall_images',{method:'POST',body:JSON.stringify({query:q,k:8})});
 const im=d.images||[];document.getElementById('pstat').textContent=im.length+' match(es)';
 document.getElementById('photos').innerHTML = im.length
  ? im.map(x=>`<div class=muted>${x.score} — ${x.path}</div>`).join('')
  : '<span class=muted>no images indexed (install pillow, then ACI indexes your photo folders)</span>';}
async function toggleObserve(){const r=await j('/observe',{method:'POST',body:JSON.stringify({enabled:document.getElementById('obsbox').checked})});
 document.getElementById('obsstat').textContent=r.observing?('· observing every '+r.interval_s+'s'):'· off';}
async function toggleClip(){await j('/consent',{method:'POST',body:JSON.stringify({scope:'CLIPBOARD',allowed:document.getElementById('clipbox').checked})});loadPolicy();}
async function focusedText(){const r=await j('/focused_text');document.getElementById('obsout').textContent=r.text?('focused: '+r.text.slice(0,90)):'(no text from focused control)';}
async function ocrScreen(){document.getElementById('obsout').textContent='OCR...';const r=await j('/ocr_screen',{method:'POST',body:JSON.stringify({})});
 document.getElementById('obsout').textContent=(r.text!=null)?('OCR '+r.chars+' chars'):(r.error||r.hint||'');}
async function ingestMail(){const host=document.getElementById('mhost').value,user=document.getElementById('muser').value,password=document.getElementById('mpass').value;if(!host||!user)return;
 document.getElementById('mailstat').textContent='connecting...';
 const r=await j('/ingest_mail',{method:'POST',body:JSON.stringify({host,user,password,limit:30})});
 document.getElementById('mailstat').textContent=(r.new!=null)?(r.new+' new, '+r.chunks+' chunks'):(r.error||r.skipped||JSON.stringify(r));refresh();}
let ARCH=[];
async function archiveFolder(){const p=document.getElementById('arcfolder').value;if(!p)return;
 document.getElementById('arcstat').textContent='compressing + indexing...';
 const r=await j('/archive',{method:'POST',body:JSON.stringify({path:p})});
 document.getElementById('arcstat').textContent=`${r.files_archived} files: ${bh(r.logical_bytes)} -> ${bh(r.stored_bytes)} (${r.compression_ratio}x, saved ${bh(r.saved_bytes)})`;
 loadArchives();refresh()}
async function loadArchives(){const s=await j('/archive_stats');ARCH=s.archives||[];
 let t=`<b>${s.files} file(s) archived</b> &middot; ${bh(s.logical_bytes)} -> ${bh(s.stored_bytes)} (${s.compression_ratio}x).`;
 if(ARCH.length){t+='<table><tr><th>file</th><th>size</th><th></th></tr>';
  ARCH.slice(0,30).forEach((a,i)=>{t+=`<tr><td>${a.path}</td><td>${bh(a.orig_size)}</td><td><button onclick="restoreArc(${i})">restore</button> <button onclick="delOrig(${i})">delete original</button></td></tr>`;});t+='</table>';}
 document.getElementById('arclist').innerHTML=t;}
async function restoreArc(i){const r=await j('/restore',{method:'POST',body:JSON.stringify({path:ARCH[i].path})});
 alert(r.verified?('restored '+bh(r.bytes)+' byte-exact -> '+r.restored):JSON.stringify(r));}
async function delOrig(i){if(!confirm('Delete the ON-DISK original? ACI keeps a compressed copy you can restore byte-exact.'))return;
 const r=await j('/delete_original',{method:'POST',body:JSON.stringify({path:ARCH[i].path})});alert(JSON.stringify(r));}
async function routeQ(){const q=document.getElementById('rq').value;if(!q)return;
 document.getElementById('rout').textContent=JSON.stringify(await j('/route',{method:'POST',body:JSON.stringify({query:q})}));}
async function loadGraph(){const g=await j('/graph');const sm={};(g.nodes||[]).forEach(n=>sm[n.id]=n.summary||n.id);
 let t=`${g.nodes.length} nodes, ${g.edges.length} links`;
 if(g.edges.length){t+='<ul>';g.edges.slice(0,25).forEach(e=>{t+=`<li>${(sm[e.source]||e.source).slice(0,40)} <i>--${e.type}--></i> ${(sm[e.target]||e.target).slice(0,40)}</li>`;});t+='</ul>';}
 else t+=' (no links yet - relate monads or ingest related content)';
 document.getElementById('graphout').innerHTML=t;}
function bh(n){n=Number(n)||0;const u=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++;}return n.toFixed(1)+' '+u[i];}
async function loadDevice(){document.getElementById('devhealth').textContent='reading device...';
 const d=await j('/device');let h='';
 (d.disks||[]).forEach(k=>{h+=`disk ${k.mount} &mdash; ${k.percent_used}% used, ${bh(k.free)} free<br>`;});
 if(d.memory)h+=`RAM ${d.memory.percent_used}% used (${bh(d.memory.available)} free)<br>`;
 if(d.battery)h+=`battery ${d.battery.percent}%${d.battery.plugged?' (plugged in)':''}${d.battery.health_percent!=null?(', health '+d.battery.health_percent+'% of design'):''}<br>`;
 if(d.cpu)h+=`CPU load ${d.cpu.load_percent}%<br>`;
 h+='<b>recommendations:</b><br>'+(d.recommendations||[]).map(r=>'&bull; '+r).join('<br>');
 document.getElementById('devhealth').innerHTML=h;}
let DUPES=[];
async function scanDupes(){const p=document.getElementById('dupfolder').value;if(!p)return;
 document.getElementById('dupstat').textContent='scanning...';
 const r=await j('/scan_dupes',{method:'POST',body:JSON.stringify({path:p})});
 DUPES=r.duplicate_groups||[];
 document.getElementById('dupstat').textContent=`${r.group_count} duplicate group(s), ${r.reclaimable_h} reclaimable`+(r.truncated?' (partial scan)':'');
 let h='';
 DUPES.slice(0,20).forEach((g,i)=>{h+=`<div style="margin-top:4px">[${bh(g.size)} &times;${g.count}] ${g.paths[0]}<br>`;
  g.paths.slice(1).forEach(pp=>{h+=`&nbsp;&nbsp;&#8627; dup: ${pp}<br>`;});
  h+=`<button onclick="cleanGroup(${i})">delete ${g.count-1} extra copy(ies)</button></div>`;});
 document.getElementById('dupresult').innerHTML=h;}
async function cleanGroup(i){const g=DUPES[i];if(!g)return;
 if(!confirm('Delete '+(g.count-1)+' duplicate copies? (keeps the first listed)'))return;
 const r=await j('/clean',{method:'POST',body:JSON.stringify({paths:g.paths.slice(1)})});
 alert('Freed '+r.freed_h+' ('+r.count+' files deleted)');scanDupes();}
refresh();
setInterval(loadActivity, 4000);   // live feed
</script></body></html>"""


# Simple, friendly, search-first page (served at "/"). The technical dashboard
# stays at "/console". This is what a regular user sees: one box, plain results,
# click to open the real file. No JSON, no tables, no jargon.
SIMPLE_HTML = """<!doctype html><html><head><meta charset=utf-8>
<title>ACI - your memory</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1117;--card:#1a1d27;--ink:#e7e9ee;--mut:#8b90a0;--acc:#6ea8fe;--line:#272b38}
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh}
.wrap{max-width:720px;margin:0 auto;padding:46px 20px 80px}
h1{font-size:27px;font-weight:650;margin:0 0 4px;letter-spacing:-.4px}
.sub{color:var(--mut);margin:0 0 26px;font-size:14px}
.searchbar{display:flex;gap:8px;position:sticky;top:0;z-index:2;padding:12px 0;background:linear-gradient(var(--bg),var(--bg) 72%,transparent)}
#q{flex:1;font-size:17px;padding:14px 16px;border-radius:14px;border:1px solid var(--line);background:var(--card);color:var(--ink);outline:none}
#q:focus{border-color:var(--acc)}
#go{font-size:16px;padding:0 22px;border-radius:14px;border:0;background:var(--acc);color:#0b1020;font-weight:600;cursor:pointer}
.chips{margin:12px 0 2px}
.chip{display:inline-block;background:var(--card);border:1px solid var(--line);color:var(--mut);padding:6px 12px;border-radius:20px;font-size:13px;margin:0 6px 6px 0;cursor:pointer}
.chip:hover{border-color:var(--acc);color:var(--ink)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px 16px;margin:11px 0}
.fn{font-weight:600;font-size:15px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.snip{color:#c7ccd8;margin:6px 0 9px;font-size:14px}
.meta{color:var(--mut);font-size:12px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.path{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:78%}
.open{background:transparent;border:1px solid var(--line);color:var(--acc);border-radius:8px;padding:4px 11px;font-size:12px;cursor:pointer;flex:none}
.open:hover{border-color:var(--acc)}
.status{color:var(--mut);font-size:13px;margin:18px 2px}
.bar{height:4px;border-radius:3px;background:var(--line);overflow:hidden;width:64px;flex:none}
.bar>i{display:block;height:100%;background:var(--acc)}
.foot{color:var(--mut);font-size:12px;margin-top:42px;text-align:center}.foot a{color:var(--mut)}
</style></head><body><div class=wrap>
<h1>Search everything you own</h1>
<p class=sub id=sub>Type what you remember - not exact words. ACI finds it by meaning.</p>
<div class=searchbar>
 <input id=q autofocus autocomplete=off placeholder="e.g. notes about monads &middot; my tax pdf &middot; the email about the deadline">
 <button id=go>Search</button></div>
<div class=chips id=chips></div>
<div id=results></div>
<div class=foot>private &middot; on your device &middot; nothing leaves your machine &mdash; <a href="http://127.0.0.1:7090">ask AIOS</a> &middot; <a href="/console">advanced console</a></div>
</div><script>
const $=s=>document.querySelector(s), R=$('#results');
const ex=["notes about monads","my legal documents","ideas for the business","emails about deadlines","photos of receipts"];
$('#chips').innerHTML=ex.map(e=>'<span class=chip>'+e+'</span>').join('');
$('#chips').onclick=e=>{if(e.target.classList.contains('chip')){$('#q').value=e.target.textContent;search();}};
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
R.onclick=e=>{const b=e.target.closest('.open');if(b){fetch('/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:b.dataset.path})}).catch(()=>{});}};
async function search(){
 const q=$('#q').value.trim(); if(!q)return;
 R.innerHTML='<div class=status>searching your memory&hellip;</div>';
 try{
  const r=await fetch('/recall',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q,k:10})});
  const hits=((await r.json()).hits)||[];
  if(!hits.length){R.innerHTML='<div class=status>Nothing found for &ldquo;'+esc(q)+'&rdquo;. Try fewer or different words.</div>';return;}
  R.innerHTML='<div class=status>'+hits.length+' results &middot; best match first</div>'+hits.map(h=>{
   const m=h.metadata||{}, fn=m.filename||m.title||h.source_type||'memory';
   const snip=(h.value||h.summary||'').slice(0,260), path=m.path||'', pct=Math.max(4,Math.round((h.score||0)*100));
   return '<div class=card><div class=fn><span>'+esc(fn)+'</span>'+
    (path?'<button class=open data-path="'+esc(path)+'">Open</button>':'')+'</div>'+
    '<div class=snip>'+esc(snip)+'</div>'+
    '<div class=meta><span class=path>'+esc(path)+'</span><span class=bar title="match strength"><i style="width:'+pct+'%"></i></span></div></div>';
  }).join('');
 }catch(e){R.innerHTML='<div class=status>Search is warming up (loading the model on first run) &mdash; try again in a few seconds.</div>';}
}
$('#go').onclick=search; $('#q').addEventListener('keydown',e=>{if(e.key==='Enter')search();});
fetch('/health').then(r=>r.json()).then(d=>{$('#sub').innerHTML=(d.monads||0).toLocaleString()+' memories indexed &middot; searchable by meaning, privately on your device';}).catch(()=>{});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not _api_key:
            return True
        key = self.headers.get("X-API-Key", "")
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:]
        return key == _api_key

    @staticmethod
    def _host_is_local(hostport: str) -> bool:
        """True if a Host/Origin value points at loopback (port stripped, IPv6 aware)."""
        h = (hostport or "").strip()
        if "://" in h:                      # Origin: strip scheme
            h = h.split("://", 1)[1]
        h = h.split("/", 1)[0]              # strip any path
        if h.startswith("["):              # IPv6 literal [::1] or [::1]:port
            host = h.split("]", 1)[0] + "]"
        else:
            host = h.rsplit(":", 1)[0] if ":" in h else h
        return host in _LOCAL_HOSTS

    def _local_guard(self) -> bool:
        """Block CSRF and DNS-rebinding against a loopback service. The Host header
        must be a loopback name (defeats DNS-rebinding, where a malicious page resolves
        its own domain to 127.0.0.1). If an Origin header is present it must also be
        loopback (defeats a remote website POSTing to 127.0.0.1 from the user's browser).
        A request with no Origin (CLI / MCP / SDK / server-to-server) is allowed — CSRF
        is a browser-only attack. Only enforced on loopback binds; a deliberate wide bind
        (ACI_HOST=0.0.0.0) is governed by ACI_API_KEY instead."""
        if _bound_host not in ("127.0.0.1", "localhost", "::1"):
            return True
        host = self.headers.get("Host", "")
        if host and not self._host_is_local(host):
            return False
        origin = self.headers.get("Origin", "")
        if origin and not self._host_is_local(origin):
            return False
        return True

    def _read(self, length):
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/home", "/search"):
            # ACI-VPU is headless backend — the ONLY human surface is AIOS.
            return self._html(
                "<!doctype html><meta charset=utf-8><title>ACI-VPU</title>"
                "<body style=\"font:15px system-ui;background:#0d0f15;color:#e9ecf3;"
                "text-align:center;padding:16vh 20px\">"
                "<h2 style=\"color:#6ea8fe;letter-spacing:.5px\">ACI-VPU</h2>"
                "<p>Cognition backend &mdash; there's no user interface here.</p>"
                "<p>Open <b>AIOS</b> &rarr; <a style=color:#6ea8fe "
                "href=\"http://127.0.0.1:7090\">http://127.0.0.1:7090</a></p>"
                "<p style=\"color:#8b91a3;font-size:12px\">(machine access is via MCP + the JSON API)</p>"
                "</body>")
        if path == "/console":
            return self._html(CONSOLE_HTML)        # dev/admin only — not a user surface
        if path == "/openapi.json":
            return self._send(200, OPENAPI)
        if not self._local_guard():
            return self._send(403, {"error": "cross-origin request refused"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        with _lock:
            if path == "/health":
                return self._send(200, {"status": "ok", "service": "ACI",
                                        "version": ACI_VERSION, "monads": _aci.store.count(),
                                        "embedder": (_aci._embedder.name
                                                     if _aci._embedder else "lazy"),
                                        "encrypted": _aci.store.crypto is not None,
                                        "paused": _aci.store.is_paused(),
                                        "observing": _aci.store.get_meta("observe") == "1"})
            if path == "/policy":
                return self._send(200, {
                    "paused": _aci.store.is_paused(),
                    "observing": _aci.store.get_meta("observe") == "1",
                    "encrypted": _aci.store.crypto is not None,
                    "encryption": (_aci.store.crypto.backend if _aci.store.crypto else "off"),
                    "kinds": ["FILE", "WEB", "AI", "CLIPBOARD", "WINDOW", "SCREEN", "EMAIL"],
                    "consent": _aci.store.consent_all()})
            if path == "/focused_text":
                return self._send(200, {"text": _redact.redact_text(_observe.focused_text() or "")[0] or None})
            if path == "/compress":
                return self._send(200, _aci.compress())
            if path == "/device":
                return self._send(200, _device.device_health())
            if path == "/archive_stats":
                return self._send(200, _archive.archive_stats(_aci))
            if path == "/integrity":
                return self._send(200, _aci.integrity())
            if path == "/activity":
                since = int(parse_qs(parsed.query).get("since", ["0"])[0])
                return self._send(200, {"events": _activity.recent(since),
                                        "counts": _activity.counts()})
            if path == "/graph":
                rels = _aci.store.all_relations()
                edges = [{"source": s, "target": t, "type": rt} for (s, t, rt, w) in rels]
                ids = {x for e in edges for x in (e["source"], e["target"])}
                nodes = []
                for mid in list(ids)[:200]:
                    m = _aci.store.get(mid)
                    if m:
                        nodes.append({"id": mid, "source_type": m.source_type,
                                      "summary": (m.summary or m.value or "")[:80]})
                return self._send(200, {"nodes": nodes, "edges": edges[:300]})
            if path == "/monads":
                qs = parse_qs(parsed.query)
                limit = int(qs.get("limit", ["50"])[0])
                stype = (qs.get("source_type", [None])[0] or None)
                return self._send(200, {"monads": [monad_view(m)
                                                   for m in _aci.list_monads(limit, source_type=stype)]})
            if path == "/watched":
                now = time.time()
                paths = _aci.store.all_watched()
                ls = {p: round(now - _last_sync[p]) for p in paths if p in _last_sync}
                return self._send(200, {"watched": paths, "last_sync": ls,
                                        "interval_s": WATCH_INTERVAL})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._local_guard():
            return self._send(403, {"error": "cross-origin request refused"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        if path == "/shutdown":
            self._send(200, {"stopping": True})
            _watch_stop.set()
            if _srv is not None:
                threading.Thread(target=_srv.shutdown, daemon=True).start()
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "payload too large"})
        if path not in REQUIRED:
            return self._send(404, {"error": "not found"})
        d = self._read(length)
        if d is None or not isinstance(d, dict):
            return self._send(400, {"error": "invalid JSON body"})
        missing = [k for k in REQUIRED[path] if not d.get(k)]
        if missing:
            return self._send(400, {"error": f"missing required field(s): {missing}"})
        if path in ("/monadise", "/recall", "/validate"):        # free-tier 3-AI cap
            _gate, _gpath = _connection_gate()
            _res = _gate.check(d.get("agent"))
            if not _res["allowed"]:
                return self._send(402, {"error": "AI connection cap reached", **_res})
            if _res.get("counted"):
                from aci import license as _lic
                _lic.save_known(_gpath, _gate.known)
        try:
            with _lock:
                if path == "/monadise":
                    m = _aci.monadise(content=d["content"],
                                      source_type=d.get("source_type", "DERIVED"),
                                      observer_id=d.get("observer"),
                                      metadata=d.get("metadata") or {},
                                      truth_value=float(d.get("truth_value", 1.0)),
                                      summary=d.get("summary"))
                    _activity.record("remember", f"stored a fact ({m.source_type})",
                                     {"summary": (m.summary or "")[:80]})
                    return self._send(200, monad_view(m))
                if path == "/assert_fact":
                    m = _aci.assert_fact(content=d["content"], fact_key=d["fact_key"],
                                         valid_from=d.get("valid_from"),
                                         source_type=d.get("source_type", "KNOWLEDGE"),
                                         observer_id=d.get("observer"),
                                         metadata=d.get("metadata") or {},
                                         truth_value=float(d.get("truth_value", 1.0)))
                    _activity.record("remember", "asserted a temporal fact",
                                     {"fact_key": d["fact_key"]})
                    return self._send(200, monad_view(m))
                if path == "/recall":
                    hits = _aci.recall(d["query"], k=int(d.get("k", 5)),
                                       as_of=d.get("as_of"),
                                       observer=build_observer(d))
                    _activity.record("recall", f"recalled {len(hits)} memory(ies) for "
                                     f"“{d['query'][:48]}”",
                                     {"top": [(h.monad.summary or "")[:60] for h in hits[:3]]})
                    return self._send(200, {"hits": [
                        {**monad_view(h.monad), "score": round(h.score, 4),
                         "similarity": round(h.similarity, 4)} for h in hits]})
                if path == "/validate":
                    r = _aci.validate(d["statement"], metadata=d.get("metadata") or {},
                                      truth_value=d.get("truth_value"),
                                      observer=build_observer(d))
                    _activity.record("ground", "checked a claim: " +
                                     ("consistent" if not r.has_contradiction else "CONTRADICTION flagged"),
                                     {"statement": d["statement"][:80]})
                    return self._send(200, {"is_consistent": r.is_consistent,
                                            "has_contradiction": r.has_contradiction,
                                            "verdict": r.verdict,
                                            "confidence": round(r.confidence, 4),
                                            "entropy": round(r.entropy, 4),
                                            "contradictions": r.contradictions, "trace": r.trace})
                if path == "/verify":
                    return self._send(200, _aci.verify_by_id(d["id"]))
                if path == "/save_skill":
                    from aci.skills import save_skill
                    v = save_skill(_aci, name=d["name"], intent=d["intent"], body=d["body"],
                                   args=d.get("args"), tags=d.get("tags"),
                                   author=d.get("author") or d.get("observer"),
                                   context=d.get("context"),
                                   truth_value=float(d.get("truth_value", 1.0)))
                    _activity.record("remember", f"saved skill '{d['name']}'",
                                     {"intent": (d.get("intent") or "")[:80]})
                    return self._send(200, v)
                if path == "/find_skills":
                    from aci.skills import find_skills
                    skills = find_skills(_aci, d["intent"], k=int(d.get("k", 5)),
                                         context=d.get("context"))
                    _activity.record("recall", f"found {len(skills)} skill(s) for "
                                     f"“{d['intent'][:48]}”", {})
                    return self._send(200, {"skills": skills})
                if path == "/skill_outcome":
                    from aci.skills import skill_outcome
                    if "success" not in d:
                        return self._send(400, {"error": "missing required field(s): ['success']"})
                    v = skill_outcome(_aci, d["skill_id"], bool(d["success"]),
                                      weight=float(d.get("weight", 1.0)))
                    if v is None:
                        return self._send(404, {"error": "skill not found",
                                                "skill_id": d.get("skill_id")})
                    return self._send(200, v)
                if path == "/log_event":
                    from aci.patterns import log_event
                    m = log_event(_aci, d["action"], target=d.get("target", ""),
                                  app=d.get("app", ""), meta=d.get("meta"))
                    return self._send(200, {"ok": m is not None,
                                            "id": getattr(m, "id", None)})
                if path == "/patterns":
                    from aci.patterns import patterns
                    return self._send(200, {"patterns": patterns(
                        _aci, min_count=int(d.get("min_count", 3)))})
                if path == "/suggest":
                    from aci.proactive import suggest
                    s = suggest(_aci, hour=d.get("hour"), dow=d.get("dow"),
                                last_action=d.get("last_action", ""), app=d.get("app", ""),
                                min_count=int(d.get("min_count", 3)))
                    return self._send(200, {"suggestion": s})
                if path == "/proactive_feedback":
                    from aci.proactive import record_feedback
                    psi = record_feedback(_aci, d["action"], bool(d["accepted"]),
                                          weight=float(d.get("weight", 1.0)))
                    return self._send(200, {"action": d["action"], "confidence": round(psi, 3)})
                if path == "/relate":
                    _aci.relate(d["source_id"], d["target_id"], d.get("type", "ASSOCIATIVE"))
                    return self._send(200, {"ok": True})
                if path == "/route":
                    return self._send(200, _aci.route(d["query"]))
                if path == "/open":                       # open the real file behind a result
                    target = (d.get("path") or "").strip()
                    if target and os.path.exists(target):
                        if os.path.isfile(target) and not _safe_to_open(target):
                            return self._send(403, {"error": "refused: only document/media files "
                                                    "may be opened (not programs or scripts)",
                                                    "path": target})
                        try:
                            os.startfile(target)          # Windows: open in the default app
                            _activity.record("open", f"opened {os.path.basename(target)}",
                                             {"path": target})
                            return self._send(200, {"opened": target})
                        except OSError as e:
                            return self._send(200, {"error": str(e), "path": target})
                    return self._send(404, {"error": "not found", "path": target})
                if path == "/forget":
                    _logsetup.audit(f"FORGET monad {d['id']}")
                    return self._send(200, {"forgotten": _aci.forget(d["id"])})
                if path == "/supersede":
                    ok = _aci.supersede(d["old_id"], d.get("new_id"), d.get("reason", ""))
                    return self._send(200, {"superseded": ok})
                if path == "/forget_by_source":
                    return self._send(200, {"removed": _aci.forget_by_source(d["path"])})
                if path == "/ingest":
                    if not _aci.store.is_allowed("FILE", os.path.abspath(d["path"])):
                        return self._send(200, {"skipped": "blocked-by-policy", "kind": "FILE"})
                    res = ingest_directory(_aci, d["path"], bool(d.get("full_resync", False)))
                    if res.get("chunks"):
                        _activity.record("capture", f"ingested folder: {res.get('chunks')} chunks "
                                         f"({res.get('new', 0)} new)", {"path": d["path"]})
                    return self._send(200, res)
                if path == "/capture":
                    domain = urlparse(d["url"]).hostname or ""
                    if not _aci.store.is_allowed("WEB", domain):
                        return self._send(200, {"skipped": "blocked-by-policy",
                                                "kind": "WEB", "domain": domain})
                    res = ingest_web(_aci, d["url"], d.get("title", ""), d["text"])
                    if res.get("chunks"):
                        _activity.record("capture", f"captured web page: {d.get('title') or domain}",
                                         {"url": d["url"][:120]})
                    return self._send(200, res)
                if path == "/watch":
                    base = os.path.abspath(d["path"])
                    if not os.path.isdir(base):
                        return self._send(400, {"error": "not a directory"})
                    _aci.store.add_watched(base)
                    if d.get("defer"):       # register only; background loop ingests it
                        return self._send(200, {"watching": base, "deferred": True})
                    stats = ingest_directory(_aci, base)
                    _last_sync[base] = time.time()
                    return self._send(200, {"watching": base, **stats})
                if path == "/unwatch":
                    _aci.store.remove_watched(os.path.abspath(d["path"]))
                    return self._send(200, {"unwatched": os.path.abspath(d["path"])})
                if path == "/pause":
                    _aci.store.set_paused(bool(d.get("paused", True)))
                    return self._send(200, {"paused": _aci.store.is_paused()})
                if path == "/consent":
                    _aci.store.consent_set(d["scope"], bool(d.get("allowed", True)),
                                           d.get("note", ""))
                    return self._send(200, {"scope": d["scope"],
                                            "allowed": _aci.store.consent_get(d["scope"])})
                if path == "/recall_images":
                    res = _aci.recall_images(d["query"], k=int(d.get("k", 8)))
                    _activity.record("recall", f"photo search “{d['query'][:40]}” -> {len(res)} image(s)")
                    return self._send(200, {"images": [
                        {"path": m.metadata.get("path"), "score": round(s, 4)} for m, s in res]})
                if path == "/scan_dupes":
                    return self._send(200, _device.scan_duplicates(
                        d["path"], int(d.get("min_size", 1 << 20))))
                if path == "/clean":
                    res = _device.clean(d["paths"])
                    if res.get("count"):
                        _activity.record("optimize", f"cleaned {res['count']} duplicate file(s), "
                                         f"freed {res.get('freed_h')}")
                    return self._send(200, res)
                if path == "/archive":
                    p = os.path.abspath(d["path"])
                    if not _aci.store.is_allowed("FILE", p):
                        return self._send(200, {"skipped": "blocked-by-policy", "kind": "FILE"})
                    if os.path.isdir(p):
                        return self._send(200, _archive.archive_directory(_aci, p))
                    return self._send(200, _archive.archive_file(_aci, p))
                if path == "/restore":
                    return self._send(200, _archive.restore_file(_aci, d["path"], d.get("dest")))
                if path == "/delete_original":
                    p = os.path.abspath(d["path"])
                    if not _aci.store.get_archive(p):
                        return self._send(400, {"error": "not archived - refusing to delete"})
                    try:
                        os.remove(p)
                        return self._send(200, {"deleted": p, "restorable": True})
                    except OSError as e:
                        return self._send(200, {"error": str(e), "path": p})
                if path == "/forget_archive":       # un-vault: drop the archive record (+GC orphan blob)
                    p = os.path.abspath(d["path"])
                    _aci.store.del_archive(p)
                    return self._send(200, {"removed": p})
                if path == "/observe":
                    _aci.store.set_meta("observe", "1" if bool(d.get("enabled", True)) else "0")
                    return self._send(200, {"observing": _aci.store.get_meta("observe") == "1",
                                            "interval_s": OBSERVE_INTERVAL})
                if path == "/ocr_screen":
                    res = _observe.capture_screen_text()
                    if res.get("text"):
                        res["text"], _n = _redact.redact_text(res["text"])
                        if _aci.store.is_allowed("SCREEN"):
                            _aci.monadise(res["text"][:4000], source_type="SCREEN",
                                          metadata={"kind": "screen"})
                    return self._send(200, res)
                if path == "/ingest_mail":
                    if not _aci.store.is_allowed("EMAIL"):
                        return self._send(200, {"skipped": "blocked-by-policy", "kind": "EMAIL"})
                    return self._send(200, _mail.ingest_imap(
                        _aci, d["host"], d["user"], d["password"],
                        d.get("folder", "INBOX"), int(d.get("limit", 50)),
                        int(d.get("port", 993))))
                if path == "/wipe":
                    if not d.get("confirm"):
                        return self._send(400, {"error": "destructive - send {\"confirm\": true}"})
                    out = _aci.wipe()
                    _logsetup.audit(f"WIPE all data ({out.get('wiped_monads')} monads)")
                    return self._send(200, out)
                if path == "/backup":
                    out = _aci.backup(d["path"])
                    _logsetup.audit(f"BACKUP -> {out.get('backup')}")
                    return self._send(200, out)
                if path == "/compact":
                    res = _aci.compact(bool(d.get("purge_superseded", False)), d.get("older_than_days"))
                    _activity.record("optimize", f"compacted store: removed {res.get('removed', 0)} monad(s)")
                    return self._send(200, res)
        except Exception as e:
            return self._send(500, {"error": "internal error", "detail": str(e)[:200]})


def main(port=None, db=None, observer=None, api_key=None, host=None):
    global _aci, _api_key, _srv, _bound_host
    # Under pythonw.exe (windowless autostart) sys.stdout/stderr are None. torch /
    # sentence-transformers / tqdm write to them on import and crash, which made ACI
    # silently fall back to the lexical embedder -> query vectors no longer matched
    # the semantic (384-dim) index -> recall returned 0 hits. Give them a sink so the
    # semantic embedder loads the same way it does under a normal console.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    # PORT env is used by most hosts (Render/Railway/Cloud Run/HF Spaces).
    port = int(port or os.environ.get("ACI_PORT") or os.environ.get("PORT", "7077"))
    # Bind 0.0.0.0 to be reachable when hosted; defaults to localhost for safety.
    host = host or os.environ.get("ACI_HOST", "127.0.0.1")
    _bound_host = host
    # Default to the real data store. (Historically this was "aci_server.db", which
    # silently started an EMPTY store beside the real ~450MB aci_data.db — the classic
    # "where did my memory go" foot-gun. The connection-gate already used aci_data.db,
    # so this also removes an internal inconsistency.)
    db = db or os.environ.get("ACI_DB", "aci_data.db")
    observer = observer or os.environ.get("ACI_OBSERVER", "observer-0")
    _api_key = api_key if api_key is not None else os.environ.get("ACI_API_KEY", "")
    _logsetup.setup(db)
    _aci = ACI(db_path=db, observer_id=observer, check_same_thread=False)
    if host not in ("127.0.0.1", "localhost", "::1") and not _api_key:
        _log.warning("SECURITY: bound to %s with no ACI_API_KEY - set a key when not on localhost.", host)
    srv = ThreadingHTTPServer((host, port), Handler)
    _srv = srv
    if os.environ.get("ACI_OBSERVE") in ("1", "true", "on"):
        _aci.store.set_meta("observe", "1")
    threading.Thread(target=_watch_loop, daemon=True).start()   # autonomy: background folder sync
    threading.Thread(target=_observe_loop, daemon=True).start()  # phase D: window/clipboard
    emb = "lazy" if _aci._embedder is None else _aci.embedder.name
    _n = _aci.store.count()
    print(f"ACI service v{ACI_VERSION} on http://{host}:{port}  "
          f"(db={os.path.abspath(db)}, {_n} monads, embedder={emb}, auth={'on' if _api_key else 'off'})")
    # Loud "where did my memory go" guard: an empty store sitting beside a much larger
    # sibling *.db almost always means the wrong ACI_DB was picked up.
    if _n == 0:
        try:
            folder = os.path.dirname(os.path.abspath(db)) or "."
            big = [f for f in os.listdir(folder)
                   if f.endswith(".db") and f != os.path.basename(db)
                   and os.path.getsize(os.path.join(folder, f)) > 1_000_000]
            if big:
                print(f"  WARNING: this store is EMPTY but larger DB(s) exist here: {big}. "
                      f"Set ACI_DB to the right file if your memory looks missing.")
        except OSError:
            pass
    print(f"Console: /console   OpenAPI: /openapi.json   "
          f"auto-watching {len(_aci.store.all_watched())} folder(s), every {WATCH_INTERVAL}s")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _watch_stop.set()
        srv.shutdown()


if __name__ == "__main__":
    main()
