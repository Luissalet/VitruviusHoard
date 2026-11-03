"""Quotes service, version 2 (fixed). Invented demo data; standard library only.

POST   /quotes                         {"customer"}                -> 201 {id, status, total_cents}
GET    /quotes/{id}                                                  -> 200 quote with lines
POST   /quotes/{id}/lines              {"description","qty","unit_cents"} -> 201 {line_id, total_cents}
DELETE /quotes/{id}/lines/{line_id}                                  -> 200 {total_cents}
POST   /quotes/{id}/discount           {"percent"}                  -> 200 {total_cents}
POST   /quotes/{id}/confirm            header Idempotency-Key       -> 200 {status, charge_id, amount_cents}
GET    /health                                                       -> 200

Totals are integer cents: round_half_up(subtotal * (100 - percent) / 100). A confirmed quote is charged once; a
retried confirmation with the same Idempotency-Key returns the stored answer, another key is refused with 409.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import sqlite3
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, customer TEXT NOT NULL, status TEXT NOT NULL,
                                   discount_pct INTEGER NOT NULL DEFAULT 0, total_cents INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS lines (id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, description TEXT NOT NULL,
                                  qty INTEGER NOT NULL, unit_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
                                    idempotency_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency (key TEXT NOT NULL, quote_id TEXT NOT NULL, response TEXT NOT NULL,
                                        PRIMARY KEY (key, quote_id));
"""


def discounted(subtotal, pct):
    return (subtotal * (100 - pct) + 50) // 100


class Service:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)

    def quote(self, qid):
        row = self.db.execute("SELECT id, customer, status, discount_pct, total_cents FROM quotes WHERE id=?", (qid,)).fetchone()
        if row is None:
            return None
        lines = [{"line_id": r[0], "description": r[1], "qty": r[2], "unit_cents": r[3]}
                 for r in self.db.execute("SELECT id, description, qty, unit_cents FROM lines WHERE quote_id=? ORDER BY rowid", (qid,))]
        return {"id": row[0], "customer": row[1], "status": row[2], "discount_pct": row[3], "total_cents": row[4], "lines": lines}

    def recompute(self, qid):
        subtotal = self.db.execute("SELECT COALESCE(SUM(qty * unit_cents), 0) FROM lines WHERE quote_id=?", (qid,)).fetchone()[0]
        pct = self.db.execute("SELECT discount_pct FROM quotes WHERE id=?", (qid,)).fetchone()[0]
        total = discounted(subtotal, pct)
        self.db.execute("UPDATE quotes SET total_cents=? WHERE id=?", (total, qid))
        return total

    def remove_line(self, qid, lid):
        row = self.db.execute("SELECT qty, unit_cents FROM lines WHERE id=? AND quote_id=?", (lid, qid)).fetchone()
        if row is None:
            return None
        self.db.execute("DELETE FROM lines WHERE id=?", (lid,))
        return self.recompute(qid)

    def confirm(self, qid, key):
        stored = self.db.execute("SELECT response FROM idempotency WHERE key=? AND quote_id=?", (key, qid)).fetchone()
        if stored is not None:
            return 200, json.loads(stored[0])
        quote = self.quote(qid)
        if quote["status"] != "draft":
            return 409, {"error": "quote is %s" % quote["status"]}
        if not quote["lines"]:
            return 409, {"error": "quote has no lines"}
        charge = "ch-" + uuid.uuid4().hex[:12]
        answer = {"id": qid, "status": "confirmed", "charge_id": charge, "amount_cents": quote["total_cents"]}
        self.db.execute("BEGIN")
        self.db.execute("INSERT INTO charges VALUES (?,?,?,?)", (charge, qid, quote["total_cents"], key))
        self.db.execute("UPDATE quotes SET status='confirmed' WHERE id=?", (qid,))
        self.db.execute("INSERT INTO idempotency VALUES (?,?,?)", (key, qid, json.dumps(answer)))
        self.db.execute("COMMIT")
        return 200, answer


def handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def payload(self):
            size = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(size) or b"{}")
            except ValueError:
                return None

        def do_GET(self):
            if self.path == "/health":
                return self.send(200, {"ok": True})
            m = re.fullmatch(r"/quotes/([\w-]+)", self.path)
            quote = service.quote(m.group(1)) if m else None
            return self.send(200, quote) if quote else self.send(404, {"error": "not found"})

        def do_POST(self):
            body = self.payload()
            if body is None:
                return self.send(400, {"error": "invalid JSON"})
            if self.path == "/quotes":
                customer = str(body.get("customer") or "").strip()
                if not customer:
                    return self.send(422, {"error": "customer is required"})
                qid = "q-" + uuid.uuid4().hex[:12]
                service.db.execute("INSERT INTO quotes (id, customer, status) VALUES (?,?,'draft')", (qid, customer))
                return self.send(201, {"id": qid, "status": "draft", "total_cents": 0})
            m = re.fullmatch(r"/quotes/([\w-]+)/(lines|discount|confirm)", self.path)
            quote = service.quote(m.group(1)) if m else None
            if quote is None:
                return self.send(404, {"error": "not found"})
            qid, what = quote["id"], m.group(2)
            if what == "confirm":
                key = self.headers.get("Idempotency-Key", "").strip()
                if not key:
                    return self.send(400, {"error": "Idempotency-Key header is required"})
                return self.send(*service.confirm(qid, key))
            if quote["status"] != "draft":
                return self.send(409, {"error": "quote is %s" % quote["status"]})
            if what == "lines":
                qty, unit = body.get("qty"), body.get("unit_cents")
                if not isinstance(qty, int) or not isinstance(unit, int) or qty < 1 or unit < 0:
                    return self.send(422, {"error": "qty >= 1 and unit_cents >= 0 are integers"})
                lid = "l-" + uuid.uuid4().hex[:12]
                service.db.execute("INSERT INTO lines VALUES (?,?,?,?,?)", (lid, qid, str(body.get("description") or ""), qty, unit))
                return self.send(201, {"line_id": lid, "total_cents": service.recompute(qid)})
            pct = body.get("percent")
            if not isinstance(pct, int) or not 0 <= pct <= 100:
                return self.send(422, {"error": "percent is an integer from 0 to 100"})
            service.db.execute("UPDATE quotes SET discount_pct=? WHERE id=?", (pct, qid))
            return self.send(200, {"total_cents": service.recompute(qid)})

        def do_DELETE(self):
            m = re.fullmatch(r"/quotes/([\w-]+)/lines/([\w-]+)", self.path)
            quote = service.quote(m.group(1)) if m else None
            if quote is None:
                return self.send(404, {"error": "not found"})
            if quote["status"] != "draft":
                return self.send(409, {"error": "quote is %s" % quote["status"]})
            total = service.remove_line(quote["id"], m.group(2))
            return self.send(404, {"error": "line not found"}) if total is None else self.send(200, {"total_cents": total})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.environ.get("QUOTES_DB", "quotes.db"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), handler(Service(args.db)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
