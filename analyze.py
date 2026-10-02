"""
Turn the radar's data into a report: what is breaking out right now, what the winners share,
how your channels compare, and experiments worth trying.

All numbers are computed here in Python. The LLM (optional) only proposes hypotheses, and a
hypothesis is dropped unless it cites titles that really are in the data it was shown -
the psych channel taught us that a model paraphrasing statistics invents conclusions.

Nothing here changes the posting pipelines. Experiments are PROPOSED; a human applies them.
(Psych channel, Aug 2026: auto-tuning on six "winners" concentrated the content and the
channel's distribution collapsed.)

    py analyze.py --data <dir>                 write reports/ + insights/, print digest
    py analyze.py --data <dir> --send          ...and send the digest to Telegram
    py analyze.py --data <dir> --send --if-due only if the last report is >20h old (CI)
"""

import argparse
import glob
import html
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone

import config
import features as F

H = 3600.0
REPO_URL = "https://github.com/maxwilliamfoster-sys/shorts-radar"


# ---------------------------------------------------------------- dataset

def load(data_dir):
    with open(os.path.join(data_dir, "state.json"), encoding="utf-8") as f:
        state = json.load(f)
    archive = []
    for p in sorted(glob.glob(os.path.join(data_dir, "archive", "*.jsonl")))[-2:]:
        with open(p, encoding="utf-8") as f:
            archive += [json.loads(line) for line in f if line.strip()]
    return state, archive


def rows(state, archive, now):
    """Unified rows: live videos (with current curve) + archived summaries from the last 21 days."""
    out = []
    for vid, v in state["videos"].items():
        c = state["channels"].get(v["c"], {})
        if c.get("relevance", 1) < config.MIN_RELEVANCE and not c.get("own"):
            continue
        age = (now - v["p"]) / H
        out.append({"id": vid, "niche": v["n"], "title": v.get("t", ""), "channel": v["c"],
                    "channel_title": c.get("title", "?"), "own": bool(c.get("own")),
                    "subs": c.get("subs"), "published": v["p"], "age_h": age,
                    "duration": v.get("d"), "views": F.latest(v), "v24": F.views_at(v, 24),
                    "v6": F.views_at(v, 6), "norm": c.get("norm_views"),
                    "outlier": F.outlier(v, c), "likes": v.get("lk"), "comments": v.get("cm"),
                    "live": True})
    for r in archive:
        if now - r["published"] > 21 * 86400:
            continue
        out.append({**r, "views": r["final"], "norm": r.get("channel_norm"),
                    "age_h": (now - r["published"]) / H, "live": False})
    return out


def pct(x):
    return f"{100 * x:.0f}%"


def fmt_views(n):
    if n is None:
        return "?"
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e4 else f"{n:,}"


# ---------------------------------------------------------------- analysis

def analyse_niche(niche, rs, state, now):
    rs = [r for r in rs if r["niche"] == niche]
    comp = [r for r in rs if not r["own"]]
    own = [r for r in rs if r["own"]]
    # "scored" = mature enough to judge (48h+) and has a channel-relative outlier score
    scored = [r for r in comp if r["outlier"] is not None and r["age_h"] >= 48]
    res = {"niche": niche, "n_videos": len(rs), "n_scored": len(scored),
           "n_channels": len({r["channel"] for r in comp})}

    # breaking now: <36h old and already past the channel's normal video
    young = [r for r in comp if r["age_h"] < 36 and r["norm"] and r["views"] >= config.MIN_VIEWS_FOR_OUTLIER]
    for r in young:
        r["early_ratio"] = r["views"] / max(r["norm"], 1)
    res["breaking"] = [_brief(r, "early_ratio") for r in
                       sorted(young, key=lambda r: -r["early_ratio"])[:6] if r["early_ratio"] >= 1.5]
    res["top_outliers"] = [_brief(r, "outlier") for r in
                           sorted(scored, key=lambda r: -r["outlier"])[:8]]

    # feature lift: share of a feature among the top quartile vs among all scored videos
    lifts = []
    if len(scored) >= 20:
        cut = sorted(r["outlier"] for r in scored)[int(len(scored) * 0.75)]
        top = [r for r in scored if r["outlier"] >= cut]
        feats_all = [F.title_features(r["title"], niche, r["duration"], r["published"]) for r in scored]
        feats_top = [F.title_features(r["title"], niche, r["duration"], r["published"]) for r in top]
        names = sorted({k for f in feats_all for k in f})
        for k in names:
            n_all = sum(1 for f in feats_all if f.get(k))
            n_top = sum(1 for f in feats_top if f.get(k))
            if n_all < config.MIN_FEATURE_N:
                continue
            share_all, share_top = n_all / len(scored), n_top / len(top)
            lift = share_top / share_all if share_all else 0
            med = statistics.median([r["outlier"] for r, f in zip(scored, feats_all) if f.get(k)])
            lifts.append({"feature": k, "lift": round(lift, 2), "share_top": round(share_top, 3),
                          "share_all": round(share_all, 3), "n": n_all, "median_outlier": round(med, 2)})
        lifts.sort(key=lambda x: -x["lift"])
        res["top_quartile_cut"] = round(cut, 2)
    res["feature_lift"] = lifts

    # words over-represented in winning titles (needs >=4 winning titles using the word)
    words = []
    if len(scored) >= 20:
        top_ids = {r["id"] for r in scored if r["outlier"] >= res["top_quartile_cut"]}
        cnt_all, cnt_top = {}, {}
        for r in scored:
            for w in F.title_terms(r["title"]):
                cnt_all[w] = cnt_all.get(w, 0) + 1
                if r["id"] in top_ids:
                    cnt_top[w] = cnt_top.get(w, 0) + 1
        for w, nt in cnt_top.items():
            if nt >= 4:
                words.append({"word": w, "lift": round((nt / len(top_ids)) / (cnt_all[w] / len(scored)), 2),
                              "in_winners": nt})
        words.sort(key=lambda x: (-x["lift"], -x["in_winners"]))
    res["winning_words"] = words[:12]

    # duration sweet spot among scored videos that have a duration
    bands = {}
    for r in scored:
        d = r["duration"]
        if d:
            b = "≤20s" if d <= 20 else "21-45s" if d <= 45 else "46-90s" if d <= 90 else ">90s"
            bands.setdefault(b, []).append(r["outlier"])
    res["duration_bands"] = {b: {"n": len(v), "median_outlier": round(statistics.median(v), 2)}
                             for b, v in bands.items() if len(v) >= config.MIN_FEATURE_N}

    # you vs the niche
    own_recent = sorted([r for r in own if r["age_h"] <= 8 * 24], key=lambda r: -r["published"])
    small = [r for r in comp if r["v24"] is not None and r["subs"] is not None and r["subs"] < 50000]
    res["you"] = {
        "videos": len(own_recent),
        "median_views": statistics.median([r["views"] for r in own_recent]) if own_recent else None,
        "median_v24": _med([r["v24"] for r in own_recent]),
        "niche_small_channels_median_v24": _med([r["v24"] for r in small]),
        "niche_small_channels_n": len(small),
        "best": _brief(max(own_recent, key=lambda r: r["views"]), None) if own_recent else None,
        "titles": [r["title"] for r in own_recent[:10]],
    }
    # winning features your recent titles under-use
    gaps = []
    if own_recent and lifts:
        own_feats = [F.title_features(r["title"], niche, r["duration"], r["published"]) for r in own_recent]
        for l in lifts:
            if l["lift"] < 1.3 or l["feature"].startswith("posted_"):
                continue
            own_share = sum(1 for f in own_feats if f.get(l["feature"])) / len(own_feats)
            if own_share < l["share_top"] / 2:
                gaps.append({**l, "own_share": round(own_share, 2)})
    res["gaps"] = gaps[:5]
    return res


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _brief(r, key):
    return {"title": r["title"], "channel": r["channel_title"], "views": r["views"],
            "ratio": round(r[key], 1) if key and r.get(key) else None,
            "age_h": round(r["age_h"]), "duration": r["duration"], "subs": r["subs"],
            "url": f"https://youtube.com/shorts/{r['id']}"}


# ---------------------------------------------------------------- LLM hypotheses (optional)

def llm_hypotheses(res):
    key = os.getenv("GROQ_API_KEY")
    if not key or len(res["top_outliers"]) < 5:
        return []
    winners = [w["title"] for w in res["top_outliers"]] + [w["title"] for w in res["breaking"]]
    prompt = (
        f"You analyse YouTube Shorts in the '{res['niche']}' niche for a small automated channel.\n"
        "Below are titles of competitor Shorts that are beating their own channel's normal views "
        "(WINNERS), a measured feature table, and the channel's own recent titles.\n\n"
        "WINNERS:\n" + "\n".join(f"- {t}" for t in winners) +
        "\n\nFEATURE LIFT (share among top quarter / share among all):\n" +
        "\n".join(f"- {l['feature']}: lift {l['lift']} (n={l['n']})" for l in res["feature_lift"][:12]) +
        "\n\nOUR RECENT TITLES:\n" + "\n".join(f"- {t}" for t in res["you"]["titles"]) +
        "\n\nPropose up to 3 concrete, testable changes for OUR channel. Each must be grounded in "
        "at least two WINNERS titles quoted EXACTLY. Do not invent numbers. Reply with JSON only: "
        '{"hypotheses":[{"change":"...","why":"...","evidence":["exact winner title","..."],'
        '"how_to_test":"..."}]}'
    )
    for model, effort in (("openai/gpt-oss-120b", "low"), ("qwen/qwen3.8-27b", "none")):
        try:
            body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1500, "temperature": 0.4, "reasoning_effort": effort,
                    "response_format": {"type": "json_object"}}
            req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",
                                         data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {key}",
                                                  "Content-Type": "application/json",
                                                  "User-Agent": "shorts-radar"})
            with urllib.request.urlopen(req, timeout=60) as r:
                content = json.loads(r.read())["choices"][0]["message"]["content"]
            hyps = json.loads(content).get("hypotheses", [])
            break
        except Exception as e:
            print(f"[llm] {model}: {e}", file=sys.stderr)
            hyps = []
    # keep only hypotheses whose evidence is real
    real = {t.strip().lower() for t in winners}
    kept = []
    for h in hyps:
        ev = [e for e in h.get("evidence", []) if isinstance(e, str) and e.strip().lower() in real]
        if len(ev) >= 2 and h.get("change"):
            kept.append({"change": h["change"], "why": h.get("why", ""), "evidence": ev,
                         "how_to_test": h.get("how_to_test", "")})
    if hyps and not kept:
        print("[llm] every hypothesis cited titles not in the data - dropped", file=sys.stderr)
    return kept[:3]


# ---------------------------------------------------------------- output

def markdown(results, state, now):
    when = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# Shorts Radar - {when}", ""]
    runs = state["meta"].get("runs", [])[-12:]
    L.append(f"Sweeps in the last day: {sum(1 for r in runs if now - r['t'] < 86400)} · "
             f"API units today: {state['meta'].get('quota', {}).get('units', 0)}/{config.QUOTA_CAP_PER_DAY}")
    L.append("")
    for res in results:
        n = res["niche"]
        L += [f"## {n.title()}", "",
              f"{res['n_channels']} competitor channels · {res['n_videos']} Shorts tracked · "
              f"{res['n_scored']} mature enough to score", ""]
        if res["n_scored"] < 40:
            L += ["> Warming up: fewer than 40 scored videos. Patterns below are not trustworthy yet.", ""]
        L += ["### Breaking now (<36h, already beating their channel's normal video)", ""]
        L += [f"- **{b['ratio']}x** · {fmt_views(b['views'])} in {b['age_h']}h · [{b['title']}]({b['url']}) · {b['channel']}"
              for b in res["breaking"]] or ["- nothing yet"]
        L += ["", "### Biggest outliers (2-8 days old)", ""]
        L += [f"- **{b['ratio']}x** · {fmt_views(b['views'])} · {b['duration'] or '?'}s · [{b['title']}]({b['url']}) · "
              f"{b['channel']} ({fmt_views(b['subs'])} subs)" for b in res["top_outliers"]] or ["- not enough data"]
        if res["feature_lift"]:
            L += ["", "### What the top quarter has in common", "",
                  "| feature | lift | in top 25% | in all | n |", "|---|---|---|---|---|"]
            L += [f"| {l['feature']} | {l['lift']}x | {pct(l['share_top'])} | {pct(l['share_all'])} | {l['n']} |"
                  for l in res["feature_lift"]]
        if res["duration_bands"]:
            L += ["", "### Length vs outlier score (median)", ""]
            L += [f"- {b}: {v['median_outlier']}x (n={v['n']})" for b, v in res["duration_bands"].items()]
        if res["winning_words"]:
            L += ["", "### Words over-represented in winning titles", "",
                  ", ".join(f"{w['word']} ({w['lift']}x)" for w in res["winning_words"])]
        y = res["you"]
        L += ["", "### You vs the niche", ""]
        if y["videos"]:
            L.append(f"- Your last {y['videos']} Shorts: median {fmt_views(y['median_views'])} views"
                     + (f", {fmt_views(y['median_v24'])} at 24h" if y["median_v24"] is not None else ""))
            if y["niche_small_channels_median_v24"] is not None:
                L.append(f"- Small competitors (<50k subs, n={y['niche_small_channels_n']}): median "
                         f"{fmt_views(y['niche_small_channels_median_v24'])} at 24h")
            if y["best"]:
                L.append(f"- Your best: {fmt_views(y['best']['views'])} · [{y['best']['title']}]({y['best']['url']})")
        else:
            L.append("- no recent uploads seen")
        if res["gaps"]:
            L += ["", "**Winning traits your recent titles rarely use:**"]
            L += [f"- `{g['feature']}`: {pct(g['share_top'])} of winners vs {pct(g['own_share'])} of yours "
                  f"(lift {g['lift']}x, n={g['n']})" for g in res["gaps"]]
        if res.get("hypotheses"):
            L += ["", "### Proposed experiments (not applied - review first)", ""]
            for h in res["hypotheses"]:
                L += [f"- **{h['change']}** - {h['why']}",
                      f"  - evidence: " + " / ".join(f"\"{e}\"" for e in h["evidence"]),
                      f"  - test: {h['how_to_test']}"]
        L.append("")
    return "\n".join(L)


def telegram_digest(results, now):
    esc = html.escape
    L = ["📡 <b>Shorts Radar</b>"]
    for res in results:
        L += ["", f"<b>{res['niche'].upper()}</b> · {res['n_scored']} scored / {res['n_videos']} tracked"]
        if res["n_scored"] < 40:
            L.append("<i>warming up - trends not reliable yet</i>")
        for b in res["breaking"][:3]:
            L.append(f"🔥 {b['ratio']}x in {b['age_h']}h · <a href=\"{b['url']}\">{esc(b['title'][:70])}</a>")
        for b in res["top_outliers"][:3]:
            L.append(f"🏆 {b['ratio']}x · {fmt_views(b['views'])} · <a href=\"{b['url']}\">{esc(b['title'][:70])}</a>")
        good = [l for l in res["feature_lift"] if l["lift"] >= 1.3][:3]
        if good:
            L.append("📈 " + ", ".join(f"{esc(l['feature'])} {l['lift']}x" for l in good))
        y = res["you"]
        if y["median_v24"] is not None and y["niche_small_channels_median_v24"] is not None:
            L.append(f"🪞 you {fmt_views(y['median_v24'])} @24h vs small rivals {fmt_views(y['niche_small_channels_median_v24'])}")
        for g in res["gaps"][:2]:
            L.append(f"🧩 winners use <code>{esc(g['feature'])}</code> {pct(g['share_top'])}, you {pct(g['own_share'])}")
        for h in res.get("hypotheses", [])[:2]:
            L.append(f"🧪 {esc(h['change'][:160])}")
    L += ["", f"<a href=\"{REPO_URL}/blob/data/reports/latest.md\">Full report</a>"]
    return "\n".join(L)


def send_telegram(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[telegram] no credentials - not sent")
        return
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                 data=json.dumps({"chat_id": chat, "text": text[:4000], "parse_mode": "HTML",
                                                  "disable_web_page_preview": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20)
    print("[telegram] sent")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--if-due", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    now = time.time()
    state, archive = load(a.data)
    if a.if_due:
        hour = datetime.now(timezone.utc).hour
        if now - state["meta"].get("last_report", 0) < 20 * H or hour < 7:
            print("[report] not due"); return
    rs = rows(state, archive, now)
    results = []
    for niche in config.NICHES:
        res = analyse_niche(niche, rs, state, now)
        res["hypotheses"] = [] if a.no_llm or res["n_scored"] < 40 else llm_hypotheses(res)
        results.append(res)
    md = markdown(results, state, now)
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    for d in ("reports", "insights"):
        os.makedirs(os.path.join(a.data, d), exist_ok=True)
    for name in (f"{day}.md", "latest.md"):
        with open(os.path.join(a.data, "reports", name), "w", encoding="utf-8") as f:
            f.write(md)
    for res in results:
        with open(os.path.join(a.data, "insights", f"{res['niche']}.json"), "w", encoding="utf-8") as f:
            json.dump({"generated": round(now), **res}, f, ensure_ascii=False, indent=1)
    digest = telegram_digest(results, now)
    print(digest)
    if a.send:
        send_telegram(digest)
    state["meta"]["last_report"] = now
    with open(os.path.join(a.data, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
