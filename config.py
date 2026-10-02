"""
What the radar watches. Edit NICHES to point it at a different market.

Data sources and their costs:
  * Channel RSS feeds (youtube.com/feeds/videos.xml) - latest 15 uploads per channel
    with exact view counts and publish times. Free, no quota. This is the workhorse:
    every run snapshots every watched channel, so we see view CURVES, not just totals.
  * yt-dlp flat extraction of hashtag pages and Shorts search - finds new channels.
    Free, no quota.
  * YouTube Data API (optional, needs token.json) - only to map a discovered video to
    its channel, get durations/likes/comments and subscriber counts. Capped at
    QUOTA_CAP_PER_DAY because the same Google project uploads the chess and reddit
    videos (~1,600 units per upload, ~8,000/day already spoken for).
"""

NICHES = {
    "chess": {
        "own_channel": "UC_2pRg4v4cQ24gdXR-CR0xQ",          # @CandidateMoves
        "hashtags": ["chesspuzzle", "chess", "chesstactics", "chessshorts"],
        "searches": ["chess puzzle", "find the best move chess", "magnus carlsen chess",
                     "mate in 2 chess"],
        # a channel stays watched only if >=30% of its Shorts mention one of these (title+description)
        "keywords": r"chess|checkmate|♟|mate in|ajedrez|xadrez|schach|échecs|шахмат|catur|cờ vua|scacchi|satran",
    },
    "reddit": {
        "own_channel": "UCKFVmbFcjKzDo9XrnZ3aerQ",          # @redditstoriesshortzz
        "hashtags": ["redditstories", "redditstory", "askreddit", "aita"],
        "searches": ["reddit stories", "aita reddit story", "reddit story revenge",
                     "reddit relationship story"],
        # story channels often never say "reddit", so relationship/family drama words count too
        "keywords": r"reddit|aita|aitah|r/|stor(y|ies)|askreddit|tifu|entitled|revenge|cheat|husband|wife|boyfriend|girlfriend|fianc|in-law|sister|brother|mom|dad",
    },
}

CHANNELS_PER_NICHE = 45        # competitor channels polled every run (by discovery hits)
MAX_SHORT_SECONDS = 180        # YouTube Shorts limit
TRACK_DAYS = 8                 # snapshot a video for this long, then archive its summary
DISCOVERY_EVERY_HOURS = 6      # yt-dlp is slow and the channel set changes slowly
DISCOVERY_PER_SOURCE = 40
QUOTA_CAP_PER_DAY = 400        # Data API units the radar may spend (Pacific-day reset ~ UTC 07/08)
SUBS_REFRESH_HOURS = 24
MIN_RELEVANCE = 0.3

# Autopilot: publish experiments the posting pipelines apply automatically (see autopilot.py).
# False clears every directive on the next report; the pipelines then run as baseline.
AUTOPILOT_ENABLED = True

# Statistics guards (lessons from the psych channel: n=6 "winners" over-fit the pipeline
# and collapsed distribution; one viral outlier dominated every average).
MIN_VIDEOS_FOR_CHANNEL_NORM = 4   # a channel needs this many 48h+ videos to score outliers
MIN_VIEWS_FOR_OUTLIER = 1000      # 30 views vs a median of 3 is not a "10x outlier"
MIN_FEATURE_N = 8                 # a title feature needs this many videos before it is shown

# Chess names worth detecting in titles (famous-player hooks are CandidateMoves' current bet).
FAMOUS_CHESS = ["magnus", "carlsen", "hikaru", "nakamura", "gotham", "levy", "fischer",
                "kasparov", "gukesh", "caruana", "firouzja", "alireza", "botez", "giri",
                "morphy", "praggnanandhaa", "pragg", "polgar", "anand", "ding liren",
                "nepo", "tal "]
