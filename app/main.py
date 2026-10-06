import pathlib, threading, time
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import agent, db, settle

app = FastAPI(title="QuickDrop Payout Dispute Desk")
STATIC = pathlib.Path(__file__).parent / "static"

def _reconciler():
    while True:
        time.sleep(5)
        try:
            with db.connect() as c: settle.reconcile(c)
        except Exception: pass

@app.on_event("startup")
def _startup():
    db.init()
    threading.Thread(target=_reconciler, daemon=True).start()

class Msg(BaseModel):
    message_id: str
    rider_id: str
    text: str
    received_at: str | None = None

@app.get("/health")
def health():
    with db.connect() as c: c.execute("select 1")
    return {"ok": True}

@app.post("/messages")
def messages(m: Msg):
    with db.connect() as conn, db.rider_lock(conn, m.rider_id):
        done = conn.execute("select reply from messages where message_id=%s", (m.message_id,)).fetchone()
        if done and done["reply"]:                         # vendor retry: same answer, nothing re-run
            db.trace(conn, m.rider_id, m.message_id, "decision", "duplicate_delivery_ignored", {"message_id": m.message_id}, {"replayed_reply": True})
            return {"reply": done["reply"]}
        conn.execute("insert into messages(message_id,rider_id,text,received_at) values(%s,%s,%s,%s) on conflict do nothing",
                     (m.message_id, m.rider_id, m.text, m.received_at))
        db.trace(conn, m.rider_id, m.message_id, "message_in", "rider_message",
                 {"message_id": m.message_id, "text": m.text, "received_at": m.received_at}, None)
        try: settle.reconcile(conn)                        # opportunistically finish earlier unconfirmed payments
        except Exception: pass
        reply = agent.run(conn, m.rider_id, m.message_id, m.text, m.received_at)
        conn.execute("update messages set reply=%s where message_id=%s", (reply, m.message_id))
        db.trace(conn, m.rider_id, m.message_id, "reply", "reply_to_rider", None, reply)
        return {"reply": reply}

@app.get("/trace/{rider_id}")
def trace(rider_id: str):
    with db.connect() as c:
        rows = c.execute("select at, type, name, input, output from trace_events where rider_id=%s order by id", (rider_id,)).fetchall()
    return [{**r, "at": r["at"].isoformat()} for r in rows]

@app.get("/ops/pending")
def pending():
    with db.connect() as c:
        rows = c.execute("select id, rider_id, type, amount, reason, created_at from approvals where status='open' order by id").fetchall()
    return [{"id": str(r["id"]), "rider_id": r["rider_id"], "type": r["type"], "amount": r["amount"], "reason": r["reason"],
             "created_at": r["created_at"].isoformat()} for r in rows]

@app.get("/ops/conversations")
def conversations():
    with db.connect() as c:
        return c.execute("select rider_id, count(*)::int n, max(created_at) last from messages group by rider_id order by last desc limit 200").fetchall()

@app.get("/ops/messages/{rider_id}")
def rider_messages(rider_id: str):
    with db.connect() as c:
        return c.execute("select message_id, text, reply, created_at from messages where rider_id=%s order by created_at", (rider_id,)).fetchall()

@app.get("/ops/disputes/{rider_id}")
def rider_disputes(rider_id: str):
    with db.connect() as c:
        return c.execute("select d.id, d.kind, d.day, d.amount, d.status, d.reason, d.finding_ids from disputes d where rider_id=%s order by id", (rider_id,)).fetchall()

class Who(BaseModel):
    who: str = "ops"

@app.post("/ops/approvals/{aid}/{action}")
def decide(aid: int, action: str, b: Who = Who()):
    if action not in ("approve", "reject", "resolve"): return {"ok": False, "error": "bad_action"}
    with db.connect() as c: return settle.ops_decide(c, aid, "approve" if action in ("approve", "resolve") else "reject", b.who)

@app.get("/")
def index(): return FileResponse(STATIC / "index.html")
