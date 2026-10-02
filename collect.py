"""
One radar sweep: (maybe) discover channels, snapshot every watched channel's Shorts via RSS,
fill in metadata from the Data API, archive videos that aged out.

    py collect.py --data <dir>          state lives in <dir>/state.json
"""

import argparse
import json
import os
import re
import statistics
import time
from datetime import datetime, timezone

import config
import features
import sources

H = 3600.0


def load(data_dir):
    p = os.path.join(data_dir, "state.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"channels": {}, "videos": {}, "meta": {}}


def save(state, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    tmp = os.path.join(data_dir, "state.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(data_dir, "state.json"))


def ensure_own(state):
    for niche, cfg in config.NICHES.items():
        c = state["channels"].setdefault(cfg["own_channel"], {"hits": {}, "first_seen": time.time()})
        c["own"] = niche


def run_discovery(state, api, now):
    if now - state["meta"].get("last_discovery", 0) < config.DISCOVERY_EVERY_HOURS * H:
        return
    if not api.ok:
        print("[discover] skipped: mapping videos to channels needs the Data API")
        return
    vid_channel = state["meta"].setdefault("vid_channel", {})   # cache: discovered video -> channel
    for niche, cfg in config.NICHES.items():
        found = sources.discover(cfg)
        unknown = [v for v in found if v not in vid_channel and v not in state["videos"]]
        for vid, info in api.videos(unknown).items():
            vid_channel[vid] = info["channel"] if (info["duration"] or 0) <= config.MAX_SHORT_SECONDS else None
        # decay, then credit channels surfacing now (max 3 per channel per round)
        for c in state["channels"].values():
            if niche in c["hits"]:
                c["hits"][niche] *= 0.9
        credit = {}
        for vid in found:
            ch = vid_channel.get(vid) or state["videos"].get(vid, {}).get("c")
            if ch:
                credit[ch] = min(3, credit.get(ch, 0) + 1)
        for ch, n in credit.items():
            c = state["channels"].setdefault(ch, {"hits": {}, "first_seen": now})
            c["hits"][niche] = c["hits"].get(niche, 0) + n
        print(f"[discover] {niche}: {len(found)} shorts surfaced, {len(credit)} channels credited")
    # keep the cache bounded
    if len(vid_channel) > 20000:
        state["meta"]["vid_channel"] = dict(list(vid_channel.items())[-10000:])
    # drop channels that stopped surfacing
    for ch in [k for k, c in state["channels"].items()
               if not c.get("own") and max(c["hits"].values(), default=0) < 0.25]:
        del state["channels"][ch]
    state["meta"]["last_discovery"] = now


def niche_of(c):
    if c.get("own"):
        return c["own"]
    return max(c["hits"], key=c["hits"].get) if c["hits"] else None


def active_channels(state):
    by_niche = {n: [] for n in config.NICHES}
    for cid, c in state["channels"].items():
        n = niche_of(c)
        # relevance scored under an older keyword list is re-checked rather than trusted
        stale = c.get("rel_kw") != config.NICHES.get(n, {}).get("keywords")
        if n in by_niche and not c.get("own") and (stale or c.get("relevance", 1) >= config.MIN_RELEVANCE):
            by_niche[n].append((c["hits"][n], cid))
    out = {}
    for n, lst in by_niche.items():
        lst.sort(reverse=True)
        out[n] = [config.NICHES[n]["own_channel"]] + [cid for _, cid in lst[:config.CHANNELS_PER_NICHE]]
    return out


def snapshot(state, actives, now):
    ok = fail = new = 0
    for niche, cids in actives.items():
        for cid in cids:
            title, entries = sources.fetch_rss(cid)
            time.sleep(0.25)
            if entries is None:
                fail += 1
                continue
            ok += 1
            c = state["channels"][cid]
            c["title"] = title
            # channel norm: median views of its Shorts aged 2-14 days (what a "normal" video does)
            norm = [e["views"] for e in entries if e["is_short"] and e["views"] is not None
                    and 48 * H <= now - e["published"] <= 14 * 86400]
            c["norm_n"] = len(norm)
            c["norm_views"] = statistics.median(norm) if norm else None
            shorts = [e for e in entries if e["is_short"]]
            if shorts and not c.get("own"):
                kw = re.compile(config.NICHES[niche]["keywords"], re.I)
                c["rel_kw"] = config.NICHES[niche]["keywords"]
                c["relevance"] = round(sum(1 for e in shorts if kw.search(e["title"] + " " + e["desc"]))
                                       / len(shorts), 2)
            c["last_short"] = max((e["published"] for e in shorts), default=c.get("last_short"))
            for e in shorts:
                if now - e["published"] > config.TRACK_DAYS * 86400 or e["views"] is None:
                    continue
                v = state["videos"].get(e["id"])
                if v is None:
                    v = state["videos"][e["id"]] = {"c": cid, "n": niche, "p": e["published"],
                                                    "s": [], "first_seen": now}
                    new += 1
                v["t"] = e["title"]
                v["desc"] = e["desc"][:300]
                v["s"].append([round(now), e["views"]])
    print(f"[rss] {ok} channels read, {fail} failed, {new} new Shorts")
    return ok, fail


def enrich(state, api, now):
    """Duration/likes/comments for new videos; one more engagement read once they pass 24h."""
    if not api.ok:
        return
    need = [vid for vid, v in state["videos"].items()
            if "d" not in v or (now - v["p"] > 24 * H and not v.get("eng24"))]
    info = api.videos(need)
    for vid, i in info.items():
        v = state["videos"][vid]
        v["d"] = i["duration"]
        v["lk"], v["cm"] = i["likes"], i["comments"]
        if now - v["p"] > 24 * H:
            v["eng24"] = True
    # channel subscriber counts, daily
    if now - state["meta"].get("last_subs", 0) > config.SUBS_REFRESH_HOURS * H:
        cids = list({v["c"] for v in state["videos"].values()})
        for cid, subs in api.subscribers(cids).items():
            if cid in state["channels"]:
                state["channels"][cid]["subs"] = subs
        state["meta"]["last_subs"] = now


def compact(v, now):
    """Keep every snapshot for the first 48h (the curve that matters), then one per 6h."""
    s, out, last = v["s"], [], None
    for t, views in s:
        if t - v["p"] <= 48 * H or last is None or t - last >= 6 * H or [t, views] == s[-1]:
            out.append([t, views]); last = t
    v["s"] = out


def archive(state, data_dir, now):
    gone = [vid for vid, v in state["videos"].items() if now - v["p"] > config.TRACK_DAYS * 86400]
    if not gone:
        return
    os.makedirs(os.path.join(data_dir, "archive"), exist_ok=True)
    path = os.path.join(data_dir, "archive", datetime.now(timezone.utc).strftime("%Y-%m") + ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        for vid in gone:
            v = state["videos"].pop(vid)
            c = state["channels"].get(v["c"], {})
            row = features.summarise(vid, v, c)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[archive] {len(gone)} videos -> {os.path.basename(path)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--token", default="token.json")
    a = ap.parse_args()
    now = time.time()
    state = load(a.data)
    ensure_own(state)
    api = sources.DataAPI(state, a.token)
    run_discovery(state, api, now)
    actives = active_channels(state)
    ok, fail = snapshot(state, actives, now)
    enrich(state, api, now)
    for v in state["videos"].values():
        compact(v, now)
    archive(state, a.data, now)
    runs = state["meta"].setdefault("runs", [])
    runs.append({"t": round(now), "rss_ok": ok, "rss_fail": fail, "videos": len(state["videos"]),
                 "units": state["meta"].get("quota", {}).get("units", 0)})
    state["meta"]["runs"] = runs[-200:]
    state["meta"]["last_collect"] = now
    save(state, a.data)
    print(f"[done] tracking {len(state['videos'])} Shorts across "
          f"{sum(len(c) for c in actives.values())} channels; "
          f"API units today {state['meta'].get('quota', {}).get('units', 0)}")


if __name__ == "__main__":
    main()
