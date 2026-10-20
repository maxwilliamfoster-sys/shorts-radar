"""
Turns one niche's analysis into a prompt the owner pastes into Claude Code.
Pure function, no I/O: analyze.py writes the result to insights/<niche>.json and Bot HQ shows it.
"""
import re
import statistics
from datetime import datetime, timezone

import history

MIN_SCORED = 40          # below this the lift table is noise (same bar as the LLM hypotheses)
MIN_LIFT = 1.1
# The data branch is public, so the local folder is not written here; Bot HQ swaps this token in.
REPO = "@@REPO@@"
NOTE = "chess_puzzle_automation.md"
RULES = ("Rules: £0 only. Never weaken or bypass the narration gate, the upload gate or the fact checks. "
         "Don't disturb running A/B tests - add new ideas as new experiments with their own control.")
ASK = ("This is the weekly radar read. The chess bot's nightly experiment loop already starts and judges tests by "
       "itself from levers.json, in the order the radar's stable patterns suggest, and it never runs more than one at "
       "a time. Read EXPERIMENTS.md, experiments.py and levers.json first: list what is running and what is queued, "
       "and leave them alone. Then propose up to 2 NEW levers worth adding to levers.json, only from the patterns that "
       "held up most of the week and that are not already queued. For each: the exact change, why the data supports it, "
       "and whether it should be judged on stay rate or views@72h. If nothing qualifies, say so. For the one you rate "
       "highest, implement it as an off-by-default lever: failing test first, a sample render "
       "(send_sample.yml with loop_values), push, and confirm the next real run is green.")


def _num(n):
    return f"{int(n):,}"


def _own_repeat(titles):
    """The capitalised name used in most of our titles, e.g. ('Magnus Carlsen', 5)."""
    count = {}
    for t in titles:
        for name in set(re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", t)):
            count[name] = count.get(name, 0) + 1
    if not count:
        return None
    name, n = max(count.items(), key=lambda kv: kv[1])
    return (name, n) if n >= 3 and n * 2 >= len(titles) else None


def _days(s):
    return f" [{s['days_above']} of {s['days_seen']} days]" if s else ""


def _example(v):
    bits = [f'"{v["title"]}"']
    if v.get("ratio"):
        bits.append(f'{v["ratio"]}x its channel\'s normal')
    bits.append(f'{_num(v["views"])} views in {v["age_h"]}h' if v.get("age_h", 99) < 48 else f'{_num(v["views"])} views')
    if v.get("duration"):
        bits.append(f'{v["duration"]}s')
    bits.append(v["url"])
    return "- " + " · ".join(bits)


def build_prompt(res, now):
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    you = res.get("you") or {}
    stab = res.get("stability") or {}
    out = [
        f"Improve my chess Shorts channel (@CandidateMoves). Repo: {REPO} (GitHub: chess-puzzle-automation).",
        "",
        f"Evidence from my Shorts Radar on {day}: {res['n_channels']} competitor channels, "
        f"{res['n_videos']} Shorts tracked, {res['n_scored']} old enough to score. "
        "Outlier score = a Short's views divided by that channel's normal Short.",
    ]

    if you.get("median_v24") is not None and you.get("niche_small_channels_median_v24"):
        out += ["", "Where I am: my last "
                f"{you['videos']} Shorts median {_num(you['median_v24'])} views at 24h; small competitors "
                f"(<50k subs, n={you.get('niche_small_channels_n', '?')}) median "
                f"{_num(you['niche_small_channels_median_v24'])}."]

    titles = you.get("titles") or []
    repeat = _own_repeat(titles)
    if repeat:
        out += ["", f"Warning: {repeat[0]} is in {repeat[1]} of {len(titles)} of my recent titles. "
                "The channel may be running one formula; check whether it is wearing out."]

    own_d = [d for d in you.get("durations") or [] if d]
    if own_d and res.get("winner_median_duration"):
        out += ["", f"Length: my Shorts run a median {statistics.median(own_d):.0f}s; the winning Shorts "
                f"run a median {res['winner_median_duration']:.0f}s."]

    if res["n_scored"] < MIN_SCORED:
        out += ["", f"Not enough scored videos yet ({res['n_scored']}) to trust any pattern; "
                "treat everything below as anecdotes."]
    else:
        levers = [l for l in res.get("feature_lift", []) if l["lift"] >= MIN_LIFT]
        if levers:
            out += ["", "What over-indexes among the top quarter of competitor Shorts "
                    "(share in winners vs share overall):"]
            out[-1] += "\n" + "\n".join(
                f"- {l['feature']}: {l['lift']}x ({round(l['share_top'] * 100)}% vs "
                f"{round(l['share_all'] * 100)}%, n={l['n']})" + _days(stab.get(l["feature"])) for l in levers[:8])
        held = [(l, stab[l["feature"]]) for l in levers if history.is_stable(stab.get(l["feature"]))]
        if held:
            out += ["", "Held up most of the week (over-indexed on most of the last 7 daily reports):"]
            out[-1] += "\n" + "\n".join(
                f"- {l['feature']}: {s['days_above']} of {s['days_seen']} days at {history.BAR}x or more" for l, s in held)
        else:
            out += ["", "No pattern has held for most of the week yet, so any lift above may be a one-day fluke. "
                    "Do not start a new test from this data alone."]
        if res.get("winning_words"):
            out += ["", "Words over-represented in winning titles: " + ", ".join(
                f"{w['word']} ({w['lift']}x)" for w in res["winning_words"][:10]) + "."]
        if res.get("gaps"):
            out += ["", "Winning traits my recent titles rarely use: " + "; ".join(
                f"{g['feature']} (winners {round(g['share_top'] * 100)}%, me {round(g.get('own_share', 0) * 100)}%)"
                for g in res["gaps"]) + "."]

    if res.get("breaking"):
        out += ["", "Breaking now (under 36h old and already beating their channel):"]
        out[-1] += "\n" + "\n".join(_example(v) for v in res["breaking"][:6])
    if res.get("top_outliers"):
        out += ["", "Biggest recent outliers:"]
        out[-1] += "\n" + "\n".join(_example(v) for v in res["top_outliers"][:6])

    if res.get("hypotheses"):
        out += ["", "The radar's own proposals (unverified; weigh them yourself):"]
        out[-1] += "\n" + "\n".join(
            f"- {h['change']}. Why: {h.get('why', '')} Test: {h.get('how_to_test', '')}" for h in res["hypotheses"])

    if titles:
        out += ["", "My recent titles:"]
        out[-1] += "\n" + "\n".join(f"- {t}" for t in titles[:10])
        if you.get("best"):
            out[-1] += f"\nBest of them: {you['best']['title']} ({_num(you['best']['views'])} views)."

    out += ["",
            "Caveats: this is correlation from a small, noisy sample, and some listed Shorts may not be chess. "
            "Do not copy competitors' titles or content; borrow the structure only. My real metric is how long "
            "viewers stay, so check performance_history.json before trusting a views-only pattern.",
            "", f"Read first: memory note {NOTE}", "", RULES, "", ASK]
    return "\n".join(out)
