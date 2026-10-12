# Shorts Radar

Watches the YouTube Shorts chess-puzzle niche around **Candidate Moves** and sends a daily report to Telegram.
It runs once a day on GitHub Actions (07:00 UTC, plus manual `workflow_dispatch`). It is read-only: it never changes
the posting pipeline. (Until 2026-10-12 it also tracked Reddit stories and ran an "autopilot" that pushed title
experiments into the pipelines; both were retired because the reddit channel was stopped and no experiment ever
reached a verdict.)

## What it does

1. **Discovers** channels whose Shorts are currently surfacing on hashtag pages and in Shorts search (yt-dlp, every 6h).
   Channels are kept only while they keep surfacing and stay on-topic.
2. **Snapshots** every watched channel's latest Shorts through its public RSS feed, which carries exact views and
   publish times and costs no API quota. Repeated snapshots give each video's view *curve*, not just a total.
3. **Scores** each Short against its own channel's normal video (median of its 2-14 day old Shorts).
   A 10x outlier on a 3k-sub channel is worth as much attention as one on a 3M-sub channel.
4. **Reports daily**: what is breaking out right now, the biggest outliers, which title/length/timing traits
   over-index among the top quarter, how your channel compares with small rivals (views at 24h), and proposed
   experiments for a human to review.

## What it deliberately does not do

- **It does not let an LLM produce numbers.** Every statistic is computed in Python. The LLM only proposes hypotheses,
  and a hypothesis is dropped unless it quotes at least two real winning titles from the data.
- **It does not see YouTube's ranking model.** Nobody outside YouTube can. It measures what the algorithm *rewards*
  in this niche, which is the part that can be learned.

## Files

| | |
|---|---|
| `config.py` | niches, seeds, limits |
| `sources.py` | RSS, yt-dlp discovery, Data API (quota-capped at `QUOTA_CAP_PER_DAY`; the uploads share the project) |
| `collect.py` | one sweep |
| `features.py` | view interpolation, outlier score, title features |
| `analyze.py` | report → `reports/latest.md`, `insights/<niche>.json`, Telegram |

Data lives on the `data` branch as a single force-pushed commit: `state.json` (live curves),
`archive/YYYY-MM.jsonl` (one row per video after 8 days, the long-term learning set), `reports/`, `insights/`.

```bash
py collect.py --data data-local
py analyze.py --data data-local            # add --send for Telegram
```

Secrets: `YOUTUBE_TOKEN` (optional; read-only use), `GROQ_API_KEY` (optional), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
