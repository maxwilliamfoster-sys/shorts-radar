"""
Start the posting workflows when a slot is due, because GitHub fires only ~1 in 3 of the
private repos' scheduled wake-ups (2026-10-03: chess got 2 of ~8 overnight).

The radar is always on, so every sweep it runs each pipeline's OWN tools/due_check.py
(downloaded with its state file, so the slot rules, the posting-time experiments and the
"already posted" logic are exactly the pipeline's), and if a slot is due and no run is
already queued or running, it dispatches the post workflow with via_radar=true. That run
goes through the pipeline's check job again on GitHub, so a stale read here cannot cause
a double post.

Needs secret RADAR_DISPATCH_TOKEN: a fine-grained PAT limited to the two pipeline repos,
Actions read/write + Contents read. Without it this script does nothing.

    py trigger.py --data <dir>
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PIPELINES = {
    "chess": {"repo": "maxwilliamfoster-sys/chess-puzzle-automation", "workflow": "post_puzzle.yml",
              "files": ["tools/due_check.py", "radar_directives.py", "performance_history.json"]},
    "reddit": {"repo": "maxwilliamfoster-sys/reddit-story-automation", "workflow": "post.yml",
               "files": ["tools/due_check.py", "radar_directives.py", "posted_state.json"]},
}
MIN_MINUTES_BETWEEN_DISPATCHES = 40      # a post run takes 3-15 min; never pile them up
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}


def _api(path, token, method="GET", body=None, raw=False):
    req = urllib.request.Request(
        "https://api.github.com/" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "shorts-radar",
                 "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if raw else (json.loads(data) if data else None)


def _alert(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                     data=json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print(f"[trigger] telegram: {e}")


def due(p, token):
    """Run the pipeline's own due_check against its current state. -> (bool, reason)"""
    with tempfile.TemporaryDirectory() as d:
        for f in p["files"]:
            os.makedirs(os.path.join(d, os.path.dirname(f)), exist_ok=True)
            with open(os.path.join(d, f), "wb") as fh:
                fh.write(_api(f"repos/{p['repo']}/contents/{f}?ref=main", token, raw=True))
        out = subprocess.run([sys.executable, os.path.join("tools", "due_check.py")], cwd=d,
                             capture_output=True, text=True, timeout=60, env={**os.environ, "GITHUB_OUTPUT": ""})
        line = next((l for l in out.stdout.splitlines() if l.startswith("due=")), "")
        if not line:
            raise RuntimeError(f"due_check gave no answer: {out.stderr.strip()[-300:]}")
        return line.startswith("due=true"), line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--dry-run", action="store_true", help="check only, never dispatch")
    a = ap.parse_args()
    token = os.getenv("RADAR_DISPATCH_TOKEN")
    if not token:
        print("[trigger] no RADAR_DISPATCH_TOKEN - posting relies on the pipelines' own crons")
        return
    path = os.path.join(a.data, "trigger.json")
    st = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    now = time.time()
    for name, p in PIPELINES.items():
        s = st.setdefault(name, {})
        try:
            runs = _api(f"repos/{p['repo']}/actions/workflows/{p['workflow']}/runs?per_page=5", token)
            busy = [r for r in runs.get("workflow_runs", []) if r["status"] in ACTIVE]
            if busy:
                print(f"[trigger] {name}: a run is already {busy[0]['status']} - leaving it")
                continue
            is_due, why = due(p, token)
            s["last_check"], s["last_reason"] = round(now), why
            if not is_due:
                print(f"[trigger] {name}: {why}")
                continue
            if now - s.get("last_dispatch", 0) < MIN_MINUTES_BETWEEN_DISPATCHES * 60:
                print(f"[trigger] {name}: due, but dispatched {(now - s['last_dispatch']) / 60:.0f} min ago - waiting")
                continue
            if a.dry_run:
                print(f"[trigger] {name}: {why} - would dispatch (dry run)")
                continue
            _api(f"repos/{p['repo']}/actions/workflows/{p['workflow']}/dispatches", token, "POST",
                 {"ref": "main", "inputs": {"via_radar": "true"}})
            s["last_dispatch"] = round(now)
            s["dispatches"] = s.get("dispatches", 0) + 1
            s.pop("error", None)
            print(f"[trigger] {name}: {why} - dispatched {p['workflow']}")
        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code} {e.reason}"
            print(f"[trigger] {name}: {msg}")
            # a bad/expired token is the one failure a human must fix - say so, once a day
            if e.code in (401, 403, 404) and now - s.get("alerted", 0) > 86400:
                _alert(f"⚠️ <b>Shorts Radar can't start the {name} posts</b> ({msg}).\n"
                       "The RADAR_DISPATCH_TOKEN may have expired or lost access. Posting falls back "
                       "to the pipeline's own crons until it is replaced.")
                s["alerted"] = round(now)
            s["error"] = msg
        except Exception as e:
            print(f"[trigger] {name}: {e}")
            s["error"] = str(e)[:200]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


if __name__ == "__main__":
    main()
