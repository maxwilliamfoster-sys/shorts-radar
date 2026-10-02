"""Fetchers: channel RSS (free), yt-dlp discovery (free), Data API (metered)."""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import config

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "m": "http://search.yahoo.com/mrss/"}


# ---------------------------------------------------------------- RSS

def fetch_rss(channel_id: str):
    """Latest ~15 uploads of a channel. Returns (channel_title, [entry]) or (None, None) on failure.
    Each entry: id, title, published (unix), views, is_short, desc."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                root = ET.fromstring(r.read())
            break
        except Exception as e:
            if attempt == 2:
                print(f"[rss] {channel_id}: {e}", file=sys.stderr)
                return None, None
            time.sleep(2 * (attempt + 1))
    title = root.findtext("a:title", default="", namespaces=NS)
    out = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        link = e.find("a:link", NS)
        href = link.get("href", "") if link is not None else ""
        stats = e.find("m:group/m:community/m:statistics", NS)
        pub = e.findtext("a:published", namespaces=NS)
        if not vid or not pub:
            continue
        out.append({
            "id": vid,
            "title": e.findtext("a:title", default="", namespaces=NS),
            "published": datetime.fromisoformat(pub).timestamp(),
            "views": int(stats.get("views", 0)) if stats is not None else None,
            "is_short": "/shorts/" in href,
            "desc": (e.findtext("m:group/m:description", default="", namespaces=NS) or "")[:400],
        })
    return title, out


# ---------------------------------------------------------------- yt-dlp discovery

def _ytdlp_flat(url: str, limit: int):
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-end", str(limit),
           "-J", "-i", "--no-warnings", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, encoding="utf-8")
        # hashtag pages often 500 on a continuation page; -i keeps what was already read
        if not p.stdout.strip():
            print(f"[yt-dlp] {url}: {p.stderr.strip()[-300:]}", file=sys.stderr)
            return []
        return json.loads(p.stdout).get("entries") or []
    except Exception as e:
        print(f"[yt-dlp] {url}: {e}", file=sys.stderr)
        return []


def discover(niche_cfg: dict):
    """Video ids currently surfacing for this niche (hashtag Shorts pages + Shorts search).
    Returns {video_id: {"title":..., "views":..., "duration":...}}; channel is resolved later."""
    found = {}
    urls = [f"https://www.youtube.com/hashtag/{h}/shorts" for h in niche_cfg["hashtags"]]
    # sp=CAISAhAJ -> type = Shorts
    urls += ["https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q) + "&sp=CAISAhAJ"
             for q in niche_cfg["searches"]]
    for u in urls:
        for e in _ytdlp_flat(u, config.DISCOVERY_PER_SOURCE):
            vid = e.get("id")
            if not vid or len(vid) != 11:
                continue
            d = e.get("duration")
            if d and d > config.MAX_SHORT_SECONDS:
                continue
            found.setdefault(vid, {"title": e.get("title"), "views": e.get("view_count"), "duration": d})
    return found


# ---------------------------------------------------------------- Data API (metered)

class DataAPI:
    """Thin wrapper that counts quota units in state['meta']['quota'] and refuses past the cap."""

    def __init__(self, state, token_path="token.json"):
        self.state = state
        self.yt = None
        if not os.path.exists(token_path):
            print("[api] no token.json - running RSS-only (no durations/subs/channel mapping)")
            return
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            creds = Credentials.from_authorized_user_file(token_path)
            if not creds.valid:
                creds.refresh(Request())
            self.yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            print(f"[api] disabled: {e}", file=sys.stderr)

    def _spend(self, units: int) -> bool:
        q = self.state["meta"].setdefault("quota", {})
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if q.get("day") != day:
            q.clear(); q.update({"day": day, "units": 0})
        if q["units"] + units > config.QUOTA_CAP_PER_DAY:
            return False
        q["units"] += units
        return True

    @property
    def ok(self):
        return self.yt is not None

    def videos(self, ids):
        """{id: {channel, channel_title, duration, likes, comments, views, published, title}}"""
        out = {}
        if not self.ok:
            return out
        ids = list(ids)
        for i in range(0, len(ids), 50):
            if not self._spend(1):
                print("[api] daily cap reached", file=sys.stderr); break
            try:
                r = self.yt.videos().list(part="snippet,contentDetails,statistics",
                                          id=",".join(ids[i:i + 50])).execute()
            except Exception as e:
                print(f"[api] videos.list: {e}", file=sys.stderr); break
            for it in r.get("items", []):
                sn, st, cd = it["snippet"], it.get("statistics", {}), it["contentDetails"]
                out[it["id"]] = {
                    "channel": sn["channelId"], "channel_title": sn.get("channelTitle"),
                    "title": sn.get("title"), "published": datetime.fromisoformat(
                        sn["publishedAt"].replace("Z", "+00:00")).timestamp(),
                    "duration": iso_duration(cd.get("duration", "")),
                    "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                }
        return out

    def subscribers(self, channel_ids):
        out = {}
        if not self.ok:
            return out
        ids = list(channel_ids)
        for i in range(0, len(ids), 50):
            if not self._spend(1):
                break
            try:
                r = self.yt.channels().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
            except Exception as e:
                print(f"[api] channels.list: {e}", file=sys.stderr); break
            for it in r.get("items", []):
                st = it.get("statistics", {})
                out[it["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
        return out


def iso_duration(s: str):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se
