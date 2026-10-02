"""Per-video measurements and title features. Pure functions, no I/O."""

import re
from datetime import datetime, timezone

import config

H = 3600.0
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐‼⁉]")
_WORD = re.compile(r"[a-z0-9']+")


# Reddit story themes. ONE definition: the radar measures competitors with these, the autopilot
# ships the same pattern to the pipeline's story picker, and judges our uploads with it too.
REDDIT_THEMES = {
    "aita": r"\baita|\baitah|asshole",
    "revenge": r"revenge",
    "family/partner": r"wife|husband|boyfriend|girlfriend|\bbf\b|\bgf\b|\bmil\b|mother|father|sister|brother|parents|fianc",
    "money/wedding": r"money|\$|inheritance|wedding|rent\b",
    "cheating": r"cheat|affair|\bex\b|ex-",
    "work/school": r"\bboss|coworker|co-worker|manager|\bjob\b|\bwork|teacher|professor|school|class\b",
    "entitled/neighbor": r"entitled|karen|neighbou?r|\bhoa\b|landlord|stranger",
}


def views_at(v, hours):
    """Views at `hours` after publish, linearly interpolated between snapshots.
    None if the curve does not cover that age (we only saw it before, or only well after)."""
    target = v["p"] + hours * H
    s = v["s"]
    if not s or s[-1][0] < target:
        return None
    prev = None
    for t, views in s:
        if t >= target:
            if prev is None:
                # first sighting is after the target age - accept if close (cron drift)
                return views if t - target <= max(4 * H, hours * H * 0.25) else None
            t0, v0 = prev
            return round(v0 + (views - v0) * (target - t0) / max(t - t0, 1))
        prev = (t, views)
    return None


def latest(v):
    return v["s"][-1][1] if v["s"] else 0


def outlier(v, c):
    """Views relative to the channel's normal video (median of its 2-14 day old Shorts).
    None when the channel norm is too thin or the video is too small to mean anything."""
    norm, n = c.get("norm_views"), c.get("norm_n", 0)
    views = latest(v)
    if not norm or n < config.MIN_VIDEOS_FOR_CHANNEL_NORM or views < config.MIN_VIEWS_FOR_OUTLIER:
        return None
    return views / max(norm, 1)


def title_features(title: str, niche: str, duration=None, published=None):
    t = title or ""
    low = t.lower()
    words = [w for w in re.sub(r"#\w+", " ", low).split() if w]
    f = {
        "question": "?" in t,
        "can_you": bool(re.search(r"\bcan (you|u)\b", low)),
        "number": bool(re.search(r"\d", re.sub(r"#\w+", "", t))),
        "emoji": bool(_EMOJI.search(t)),
        "caps_word": bool(re.search(r"\b[A-Z]{3,}\b", t)),
        "hashtags_in_title": "#" in t,
        "first_person": bool(re.search(r"\b(i|my|me|i'm|we)\b", low)),
        "second_person": bool(re.search(r"\b(you|your|u)\b", low)),
        "short_title(<=6w)": len(words) <= 6,
        "long_title(>=12w)": len(words) >= 12,
    }
    if niche == "chess":
        f["famous_player"] = any(n in low + " " for n in config.FAMOUS_CHESS)
        f["mate_in_n"] = bool(re.search(r"mate in \d|checkmate in", low))
        f["brilliant/blunder"] = bool(re.search(r"brilliant|blunder|genius|insane|trap", low))
    if niche == "reddit":
        for name, pat in REDDIT_THEMES.items():
            f[name] = bool(re.search(pat, low))
        f["pov/story_hook"] = bool(re.search(r"\bpov\b|storytime|story time", low))
    if duration:
        f["dur<=20s"] = duration <= 20
        f["dur21-45s"] = 20 < duration <= 45
        f["dur46-90s"] = 45 < duration <= 90
        f["dur>90s"] = duration > 90
    if published:
        hr = datetime.fromtimestamp(published, timezone.utc).hour
        f[f"posted_{(hr // 6) * 6:02d}-{(hr // 6) * 6 + 6:02d}utc"] = True
    return f


def title_terms(title: str):
    stop = {"the", "a", "an", "to", "of", "and", "in", "is", "it", "this", "that", "for", "on",
            "my", "i", "you", "me", "with", "was", "be", "at", "he", "she", "her", "his", "they",
            "shorts", "short", "what", "when", "how", "can", "your", "u", "so", "but", "are",
            "just", "after", "from", "not", "all", "our", "we", "if", "or", "by", "do", "as"}
    low = re.sub(r"#\w+", " ", (title or "").lower())
    return {w for w in _WORD.findall(low) if w not in stop and len(w) > 2}


def summarise(vid, v, c):
    """Archive row written when a video ages out of tracking - the long-term learning set."""
    return {
        "id": vid, "niche": v["n"], "channel": v["c"], "channel_title": c.get("title"),
        "own": bool(c.get("own")), "subs": c.get("subs"), "title": v.get("t"),
        "published": v["p"], "duration": v.get("d"), "likes": v.get("lk"), "comments": v.get("cm"),
        "v6": views_at(v, 6), "v24": views_at(v, 24), "v48": views_at(v, 48), "v7d": views_at(v, 168),
        "final": latest(v), "channel_norm": c.get("norm_views"), "outlier": outlier(v, c),
    }
