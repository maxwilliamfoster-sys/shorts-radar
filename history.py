"""
Day-by-day feature lifts, so a weekly read can tell a lasting pattern from a one-day fluke.
Pure functions plus one reader for the old markdown reports (used once, to seed the history).
"""
import os
import re
from datetime import date, timedelta

KEEP_DAYS = 60
WINDOW_DAYS = 7
BAR = 1.1               # a feature "over-indexes" at this lift or more (same bar as coach.MIN_LIFT)
MIN_DAYS_SEEN = 5
MIN_SHARE_ABOVE = 0.7

_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([0-9.]+)x\s*\|")


def update(hist, day, lifts):
    hist[day] = dict(lifts)
    for old in sorted(hist)[:-KEEP_DAYS]:
        del hist[old]
    return hist


def stability(hist, today):
    """{feature: {days_above, days_seen}} over the WINDOW_DAYS days ending `today`."""
    end = date.fromisoformat(today)
    first = end - timedelta(days=WINDOW_DAYS - 1)
    out = {}
    for day, lifts in hist.items():
        if not first <= date.fromisoformat(day) <= end:
            continue
        for feature, lift in lifts.items():
            s = out.setdefault(feature, {"days_above": 0, "days_seen": 0})
            s["days_seen"] += 1
            s["days_above"] += lift >= BAR
    return out


def is_stable(s):
    return bool(s) and s["days_seen"] >= MIN_DAYS_SEEN and s["days_above"] / s["days_seen"] >= MIN_SHARE_ABOVE


def seed_from_reports(reports_dir):
    """Rebuild history from dated reports/YYYY-MM-DD.md (the feature table's lift column)."""
    hist = {}
    for name in sorted(os.listdir(reports_dir)):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name):
            continue
        lifts = {}
        with open(os.path.join(reports_dir, name), encoding="utf-8") as f:
            for line in f:
                m = _ROW.match(line)
                if m and m.group(1) != "feature":
                    lifts[m.group(1)] = float(m.group(2))
        if lifts:
            hist[name[:-3]] = lifts
    return hist
