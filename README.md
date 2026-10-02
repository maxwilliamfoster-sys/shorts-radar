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

## Autopilot: changes applied automatically, as experiments

`autopilot.py` publishes `directives/<niche>.json` on the `data` branch. The chess and reddit pipelines read it at
upload time through `radar_directives.py` and apply it themselves.

- **What qualifies:** a trait over-indexes among the top quarter of competitor Shorts (lift ≥1.3, n ≥12) and your
  titles rarely use it. It must also qualify in two reports at least 20h apart.
- **Levers it can touch:** chess titles (mate-in-N tag, emoji, hashtags); reddit titles (emoji), which story the
  editor picks (family/partner, revenge, AITA, money/wedding themes), and story length (44s). It never touches puzzle
  facts, the narration gate, quality gates, cadence or privacy.
- **Rollout:** each change starts on 50% of uploads, so the rest are a live control group. One change per lever,
  at most two per channel.
- **Judging:** after ≥6 treated and ≥6 control uploads reach 48h, treated ≥1.2x control is promoted to 75% (never
  100%; variety is a ranking input). Treated <0.8x is retired with a 14-day cooldown. Anything not clearly winning
  after 30 days is retired too.
- **Fail-safe:** directives older than 72h, unknown levers or fetch errors leave the pipeline on baseline.
  To switch off, set `AUTOPILOT_ENABLED = False` in `config.py` (clears everything on the next report), or set
  `RADAR_AUTOPILOT=0` in a pipeline.
- **Reporting:** every start, promotion and retirement is announced in the Telegram report.

This design exists because of the psych channel (Aug 2026): hard-coding what six "winners" shared concentrated
the content, and distribution collapsed.

## What it deliberately does not do

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
| `autopilot.py` | starts, promotes and retires experiments → `directives/<niche>.json` |

Data lives on the `data` branch as a single force-pushed commit: `state.json` (live curves),
`archive/YYYY-MM.jsonl` (one row per video after 8 days, the long-term learning set), `reports/`, `insights/`.

```bash
py collect.py --data data-local
py analyze.py --data data-local            # add --send for Telegram
```

Secrets: `YOUTUBE_TOKEN` (optional; read-only use), `GROQ_API_KEY` (optional), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
