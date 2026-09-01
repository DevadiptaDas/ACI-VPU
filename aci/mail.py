"""
Phase D4 - app connector: email over IMAP (stdlib only).

Pulls recent messages from any IMAP server and monadises them, so your mail becomes
part of ACI's semantic memory alongside files and the web. Credentials are passed to
the LOCAL service and used to connect directly to your mail server - they are not
stored or sent anywhere else. Incremental: each message is keyed by Message-ID so
re-running only ingests new mail.
"""
from __future__ import annotations
import email
import imaplib
from email.header import decode_header

from .documents import chunk


def _dec(raw) -> str:
    if not raw:
        return ""
    out = []
    for part, enc in decode_header(raw):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", "ignore"))
        else:
            out.append(part)
    return "".join(out)


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
               "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return msg.get_payload() if isinstance(msg.get_payload(), str) else ""


def ingest_imap(aci, host, user, password, folder="INBOX", limit=50, port=993) -> dict:
    M = imaplib.IMAP4_SSL(host, port)
    try:
        M.login(user, password)
        M.select(folder, readonly=True)
        typ, data = M.search(None, "ALL")
        ids = data[0].split()[-int(limit):]
        new = skipped = chunks = 0
        for i in ids:
            typ, md = M.fetch(i, "(RFC822)")
            if not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            subj = _dec(msg.get("Subject"))
            frm = _dec(msg.get("From"))
            date = msg.get("Date", "")
            mid = msg.get("Message-ID") or f"{frm}|{subj}|{date}"
            src = "mail:" + mid
            if aci.store.get_source_fp(src) is not None:
                skipped += 1
                continue
            text = f"Email from {frm}\nSubject: {subj}\nDate: {date}\n\n{_body(msg)}".strip()
            for ci, piece in enumerate(chunk(text)):
                aci.monadise(piece, source_type="EMAIL",
                             metadata={"path": src, "from": frm, "subject": subj,
                                       "date": date, "kind": "email", "chunk": str(ci)},
                             summary=f"{subj or '(no subject)'}: {piece.strip()[:100]}")
                chunks += 1
            aci.store.set_source_fp(src, mid)
            new += 1
        return {"folder": folder, "new": new, "skipped": skipped, "chunks": chunks,
                "scanned": len(ids)}
    finally:
        try:
            M.logout()
        except Exception:
            pass
