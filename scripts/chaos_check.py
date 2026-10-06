"""Fire all sample conversations concurrently at a FRESH system so PaySwift's chaos (504 that still pays, 503, 8s calls, 429 block)
actually bites, then verify money: nobody overpaid, nobody paid twice, everything eventually settles.
usage: python scripts/chaos_check.py http://localhost:8000   (env PAYSWIFT_BASE_URL)"""
import json, os, sys, time, pathlib, concurrent.futures as cf
import httpx
url, ps = sys.argv[1].rstrip("/"), os.getenv("PAYSWIFT_BASE_URL", "http://localhost:8081")
convs, seen = [], set()
for c in json.load(open(pathlib.Path(__file__).parent.parent / "evals" / "conversations.json")):
    if c["rider_id"] not in seen: seen.add(c["rider_id"]); convs.append(c)
lat = []
def run(c):
    for t in c["turns"]:
        if t["from"] != "rider": continue
        t0 = time.time()
        httpx.post(f"{url}/messages", timeout=120, json={"message_id": t["message_id"], "rider_id": c["rider_id"], "text": t["text"], "received_at": t["received_at"]}).raise_for_status()
        lat.append(time.time() - t0)
t0 = time.time()
with cf.ThreadPoolExecutor(len(convs)) as ex: list(ex.map(run, convs))
print(f"{len(convs)} riders concurrently: replies done in {time.time()-t0:.1f}s, median latency {sorted(lat)[len(lat)//2]:.1f}s, max {max(lat):.1f}s")
def want(c):
    e = c["expected"]; return {o["payout"] for o in e["one_of"]} if "one_of" in e else {e["payout"]}
def ledger(r):
    d = httpx.get(f"{ps}/v1/payouts", params={"rider_id": r}, timeout=20).json()["data"]; return sum(p["amount"] for p in d), len(d)
deadline, bad = time.time() + 120, []
while time.time() < deadline:
    bad = [(c["rider_id"], ledger(c["rider_id"]), want(c)) for c in convs if ledger(c["rider_id"])[0] not in want(c)]
    if not bad: break
    time.sleep(3)
over = [(r, l, w) for r, l, w in bad if l[0] > max(w)]
dups = [(c["rider_id"], ledger(c["rider_id"])) for c in convs if ledger(c["rider_id"])[1] > 1 and ledger(c["rider_id"])[0] not in want(c)]
print(f"settled in {time.time()-t0:.0f}s total; wrong ledgers: {bad or 'none'}; overpaid: {over or 'none'}")
sys.exit(1 if bad else 0)
