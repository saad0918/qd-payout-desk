import subprocess, sys, time, urllib.request
subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-U", "qd", "-d", "qd", "-c",
                "truncate messages, trace_events, approvals, payouts, disputes restart identity cascade"], check=True, capture_output=True)
subprocess.run(["docker", "compose", "restart", "payswift"], check=True, capture_output=True)
for _ in range(80):
    try:
        urllib.request.urlopen("http://localhost:8081/health", timeout=2)
        sys.exit(0)
    except Exception:
        time.sleep(0.5)
sys.exit("payswift did not come back")
