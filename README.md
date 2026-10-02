# Shorts Radar

Watches the YouTube Shorts market around two automated channels, **Candidate Moves** (chess puzzles) and **Reddit stories**.
It runs every 2 hours on GitHub Actions and sends a daily report to Telegram.

## What it does

1. **Discovers** channels whose Shorts are currently surfacing on hashtag pages and in Shorts search (yt-dlp, every 6h).
   Channels are kept only while they keep surfacing and stay on-topic.
2. **Snapshots** every watched channel's latest Shorts through its public RSS feed, which carries exact views and
   publish times and costs no API quota. Repeated snapshots give each video's view *curve*, not just a total.
3. **Scores** each Short against its own channel's normal video (median of its 2-14 day old Shorts).
   A 10x outlier on a 3k-sub channel is worth as much attention as one on a 3M-sub channel.
4. **Reports daily**: what is breaking out right now, the biggest outliers, which title/length/timing traits
   over-index among the top quarter, how your channels compare with small rivals, and proposed experiments.

## What it deliberately does not do

- **It does not change the posting pipelines.** Experiments are proposed, and a person applies them.
  On the psych channel (Aug 2026), auto-tuning on six "winners" concentrated the content and distribution collapsed.
- **It does not let an LLM produce numbers.** Every statistic is computed in Python. The LLM only proposes hypotheses,
  and a hypothesis is dropped unless it quotes at least two real winning titles from the data.
- **It does not see YouTube's ranking model.** Nobody outside YouTube can. It measures what the algorithm *rewards*
  in this niche, which is the part that can be learned.

## Files

| | |
|---|---|
| `config.py` | niches, seeds, limits |
| `sources.py` | RSS, yt-dlp discovery, Data API (quota-capped at 400 units/day; the uploads share the project) |
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
