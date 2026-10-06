import json, sys, urllib.request as u
rider = sys.argv[1]
base = "http://localhost:8000"
get = lambda p: json.load(u.urlopen(base + p))
print("=== TRACE")
for e in get("/trace/" + rider):
    print(e["type"], "|", e["name"])
    print("   in :", json.dumps(e["input"], ensure_ascii=False)[:500])
    print("   out:", json.dumps(e["output"], ensure_ascii=False)[:1200])
print("=== PENDING (escalation reasons)")
for p in get("/ops/pending"):
    if p["rider_id"] == rider: print(p["type"], p["amount"], "|", p["reason"])
print("=== REPLIES")
for m in get("/ops/messages/" + rider): print("rider:", m["text"], "\n  bot:", m["reply"])
