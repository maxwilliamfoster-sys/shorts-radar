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
    QUOTA_CAP_PER_DAY because the same Google project is used for uploads
    (~1,600 units per upload).
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
}

CHANNELS_PER_NICHE = 45        # competitor channels polled every run (by discovery hits)
MAX_SHORT_SECONDS = 180        # YouTube Shorts limit
TRACK_DAYS = 8                 # snapshot a video for this long, then archive its summary
DISCOVERY_EVERY_HOURS = 6      # with the daily run this means: discover on every run
DISCOVERY_PER_SOURCE = 40
QUOTA_CAP_PER_DAY = 700        # Data API units the radar may spend (the uploads use ~1,600 each; room left: ~2,000)
FALLBACK_UNITS_PER_SWEEP = 10  # RSS-outage fallback: up to 500 tracked videos per sweep
SUBS_REFRESH_HOURS = 20        # < 24 so the once-a-day run always refreshes despite cron jitter
MIN_RELEVANCE = 0.3

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
