"""
Autopilot: turns the radar's findings into changes the posting pipelines apply by themselves,
then checks each change against YOUR channel's own views and undoes it if it does not pay.

Why it is built as experiments, not "copy the winners":
  The psych channel (Aug 2026) hard-coded what six winning videos had in common; the
  content homogenised and distribution collapsed. So every change here:
    * only touches levers in LEVERS (title wording, which story is picked, story length) -
      never puzzle facts, the narration gate, cadence, privacy or the upload itself;
    * starts on 50% of uploads, so the other half is a live control group;
    * is promoted to at most 75% (never 100% - variety is itself a ranking input);
    * is judged on the channel's own views at 48h, treated vs control, and RETIRED if
      treated videos do worse (cooldown 14 days), or after 30 days without a clear win;
    * expires on the pipeline side if the radar stops publishing (directives older than
      72h are ignored), so a dead radar means "back to baseline", not "frozen experiment".

Directives are published at
  https://raw.githubusercontent.com/maxwilliamfoster-sys/shorts-radar/data/directives/<niche>.json
and read by radar_directives.py in each pipeline repo.
"""

import json
import os
import statistics
import time

import config
import features as F

H, DAY = 3600.0, 86400.0

# radar feature -> pipeline lever. Only these can ever be switched on automatically.
LEVERS = {
    "chess": {
        "mate_in_n":         {"lever": "title_mate_in", "eval_on": "title"},
        "emoji":             {"lever": "title_emoji", "eval_on": "title"},
        "hashtags_in_title": {"lever": "title_hashtags", "eval_on": "title"},
    },
    "reddit": {
        "emoji":          {"lever": "title_emoji", "eval_on": "title"},
        "family/partner": {"lever": "story_theme", "eval_on": "title+desc"},
        "revenge":        {"lever": "story_theme", "eval_on": "title+desc"},
        "aita":           {"lever": "story_theme", "eval_on": "title+desc"},
        "money/wedding":  {"lever": "story_theme", "eval_on": "title+desc"},
        "dur21-45s":      {"lever": "length_target", "params": {"seconds": 44}, "eval_on": "duration"},
    },
}
# Same regexes as features.title_features, shipped to the pipeline so "story about family"
# means exactly what the radar measured.
THEME_PATTERNS = {
    "family/partner": r"wife|husband|boyfriend|girlfriend|\bbf\b|\bgf\b|\bmil\b|mother|father|sister|brother|parents|fianc",
    "revenge": r"revenge",
    "aita": r"\baita|\baitah|asshole",
    "money/wedding": r"money|\$|inheritance|wedding|rent",
}

MIN_SCORED = 60          # niche needs this many scored videos before anything is switched on
MIN_LIFT = 1.3
START_NOW_MIN_LIFT = 1.25  # one-off kick-off (analyze.py --start-now): no confirmation wait, slightly lower bar
MIN_N = 12
MIN_SHARE_TOP = 0.12
CONFIRM_HOURS = 20       # a feature must qualify in two reports at least this far apart
MAX_ACTIVE = 2
START_SHARE, MAX_SHARE = 0.5, 0.75
MIN_ARM = 6              # matured own videos needed in each arm before judging
MIN_CONTROL_VIEWS = 20   # below this the channel is not being served at all - nothing to compare
WIN, LOSE = 1.2, 0.8
MAX_TEST_DAYS = 30
COOLDOWN_DAYS = 14


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _own_outcomes(niche, state, archive, since, now):
    """Own uploads published since `since`, aged 48h+, with views at 48h."""
    own_id = config.NICHES[niche]["own_channel"]
    out = []
    for vid, v in state["videos"].items():
        if v["c"] == own_id and v["p"] >= since and now - v["p"] >= 48 * H:
            v48 = F.views_at(v, 48)
            if v48 is not None:
                out.append({"title": v.get("t", ""), "desc": v.get("desc", ""), "duration": v.get("d"),
                            "published": v["p"], "v48": v48})
    for r in archive:
        if r["channel"] == own_id and r["published"] >= since and r.get("v48") is not None:
            out.append({"title": r["title"] or "", "desc": "", "duration": r.get("duration"),
                        "published": r["published"], "v48": r["v48"]})
    return out


def _treated(video, feature, niche, eval_on):
    if eval_on == "duration":
        f = F.title_features("", niche, video["duration"])
    else:
        text = video["title"] + (" " + video["desc"] if eval_on == "title+desc" else "")
        f = F.title_features(text, niche)
    return bool(f.get(feature))


def evaluate(d, niche, state, archive, now):
    """-> (verdict, detail). verdict in keep|promote|retire."""
    vids = _own_outcomes(niche, state, archive, d["since"], now)
    lev = LEVERS[niche][d["feature"]]
    t = [v["v48"] for v in vids if _treated(v, d["feature"], niche, lev["eval_on"])]
    c = [v["v48"] for v in vids if not _treated(v, d["feature"], niche, lev["eval_on"])]
    detail = {"treated_n": len(t), "control_n": len(c),
              "treated_median": statistics.median(t) if t else None,
              "control_median": statistics.median(c) if c else None}
    age_days = (now - d["since"]) / DAY
    if len(t) >= MIN_ARM and len(c) >= MIN_ARM:
        cm, tm = detail["control_median"], detail["treated_median"]
        if cm >= MIN_CONTROL_VIEWS:
            ratio = tm / cm
            detail["ratio"] = round(ratio, 2)
            if ratio < LOSE:
                return "retire", {**detail, "reason": f"treated {ratio:.2f}x control"}
            if ratio >= WIN and d["share"] < MAX_SHARE:
                return "promote", detail
    if age_days > MAX_TEST_DAYS:
        return "retire", {**detail, "reason": f"no clear win after {MAX_TEST_DAYS} days"}
    return "keep", detail


def run(results, state, archive, data_dir, now=None, start_now=False):
    """Update experiments from today's analysis. Returns human-readable change lines."""
    now = now or time.time()
    path = os.path.join(data_dir, "autopilot.json")
    ap = _load(path, {"active": {}, "candidates": {}, "retired": {}, "log": []})
    changes = []
    if not config.AUTOPILOT_ENABLED:
        for niche in config.NICHES:
            ap["active"][niche] = []
        changes.append("autopilot disabled in config - all directives cleared")
    for res in results if config.AUTOPILOT_ENABLED else []:
        niche = res["niche"]
        active = ap["active"].setdefault(niche, [])
        retired = ap["retired"].setdefault(niche, {})
        cands = ap["candidates"].setdefault(niche, {})

        # 1. judge running experiments
        for d in list(active):
            verdict, detail = evaluate(d, niche, state, archive, now)
            d["last_eval"] = detail
            if verdict == "retire":
                active.remove(d)
                retired[d["feature"]] = {"until": now + COOLDOWN_DAYS * DAY, **detail}
                changes.append(f"{niche}: ⏹ retired <b>{d['feature']}</b> ({detail.get('reason')})")
            elif verdict == "promote":
                d["share"] = MAX_SHARE
                changes.append(f"{niche}: ⬆ <b>{d['feature']}</b> beat control "
                               f"({detail['ratio']}x) - now on {int(MAX_SHARE * 100)}% of uploads")

        # 2. start new ones from features that keep qualifying
        if res["n_scored"] >= MIN_SCORED:
            gaps = {g["feature"]: g for g in res["gaps"]}
            min_lift = START_NOW_MIN_LIFT if start_now else MIN_LIFT
            qualifying = [l for l in res["feature_lift"]
                          if l["feature"] in LEVERS[niche] and l["lift"] >= min_lift and l["n"] >= MIN_N
                          and l["share_top"] >= MIN_SHARE_TOP and l["feature"] in gaps]
            q_names = {l["feature"] for l in qualifying}
            for k in list(cands):
                if k not in q_names:
                    del cands[k]          # must qualify in CONSECUTIVE reports
            for l in qualifying:
                k = l["feature"]
                first = cands.setdefault(k, now)
                busy = {d["feature"] for d in active}
                levers_busy = {d["lever"] for d in active}     # one experiment per lever at a time
                lev = LEVERS[niche][k]
                cooling = retired.get(k, {}).get("until", 0) > now
                if ((start_now or now - first >= CONFIRM_HOURS * H) and k not in busy and not cooling
                        and lev["lever"] not in levers_busy and len(active) < MAX_ACTIVE):
                    params = dict(lev.get("params", {}))
                    if lev["lever"] == "story_theme":
                        params["pattern"] = THEME_PATTERNS[k]
                    active.append({"feature": k, "lever": lev["lever"], "params": params,
                                   "share": START_SHARE, "since": now,
                                   "evidence": {"lift": l["lift"], "n": l["n"],
                                                "winners_share": l["share_top"],
                                                "your_share": gaps[k]["own_share"]}})
                    changes.append(f"{niche}: ▶ testing <b>{k}</b> on {int(START_SHARE * 100)}% of uploads "
                                   f"(winners {int(l['share_top'] * 100)}% vs yours "
                                   f"{int(gaps[k]['own_share'] * 100)}%, lift {l['lift']}x, n={l['n']})")
                    del cands[k]

    # 3. publish directives (always, so the timestamp stays fresh)
    os.makedirs(os.path.join(data_dir, "directives"), exist_ok=True)
    for niche in config.NICHES:
        with open(os.path.join(data_dir, "directives", f"{niche}.json"), "w", encoding="utf-8") as f:
            json.dump({"generated": round(now), "niche": niche,
                       "directives": [{k: d[k] for k in ("feature", "lever", "params", "share", "since")}
                                      for d in ap["active"].get(niche, [])]}, f, indent=1)
    for c in changes:
        ap["log"].append({"t": round(now), "change": c})
    ap["log"] = ap["log"][-300:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ap, f, ensure_ascii=False, indent=1)
    return changes, ap
