import json, pathlib, time, psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from contextlib import contextmanager
from . import config

def connect():
    return psycopg.connect(config.DATABASE_URL, autocommit=True, row_factory=dict_row)

def init():
    sql = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    for _ in range(60):
        try:
            with connect() as c:
                c.execute("select pg_advisory_lock(4242)")
                try: c.execute(sql)
                finally: c.execute("select pg_advisory_unlock(4242)")
            return
        except psycopg.OperationalError:
            time.sleep(1)
    raise RuntimeError("database not reachable")

@contextmanager
def rider_lock(conn, rider_id):
    """Serialise all work for one rider across workers: limits, dedupe and state can't race."""
    conn.execute("select pg_advisory_lock(hashtext(%s))", ("rider:" + rider_id,))
    try: yield
    finally: conn.execute("select pg_advisory_unlock(hashtext(%s))", ("rider:" + rider_id,))

def trace(conn, rider_id, message_id, type_, name, input_=None, output=None):
    """type: message_in | tool_call | decision | reply | error  (shape required by SUBMISSION.md)"""
    conn.execute("insert into trace_events(rider_id,message_id,type,name,input,output) values(%s,%s,%s,%s,%s,%s)",
                 (rider_id, message_id, type_, name,
                  Jsonb(input_, dumps=lambda o: json.dumps(o, default=str)),
                  Jsonb(output, dumps=lambda o: json.dumps(o, default=str))))

@contextmanager
def try_rider_lock(conn, rider_id):
    """Non-blocking variant for background work: yields True if acquired."""
    got = conn.execute("select pg_try_advisory_lock(hashtext(%s)) as g", ("rider:" + rider_id,)).fetchone()["g"]
    try: yield got
    finally:
        if got: conn.execute("select pg_advisory_unlock(hashtext(%s))", ("rider:" + rider_id,))
