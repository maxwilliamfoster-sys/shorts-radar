#!/usr/bin/env bash
# Continuous radar: sweep every INTERVAL_SECONDS until LOOP_SECONDS have passed, saving the
# data branch after every sweep, then the workflow starts the next run of itself.
#
# Every sweep: collect (RSS curves, discovery every 6h) -> analyze + autopilot (experiments
# are judged and started on every sweep; changes go to Telegram immediately; the full digest
# once a day) -> force-push the data branch (one commit, no history growth).
set -u
LOOP_SECONDS=${LOOP_SECONDS:-19800}       # 5.5h; the job timeout is 6h
INTERVAL=${INTERVAL_SECONDS:-1800}        # 30 min
END=$((SECONDS + LOOP_SECONDS))
REMOTE="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
FAILS=0
FIRST=1

git clone -q --depth 1 --branch data "$REMOTE" data 2>/dev/null || mkdir -p data
rm -rf data/.git

save_data() {
  [ -f data/state.json ] || return 1
  (
    cd data &&
    rm -rf .git &&
    git init -q -b data &&
    git config user.name "shorts-radar" &&
    git config user.email "actions@users.noreply.github.com" &&
    git add -A &&
    git commit -qm "radar data $(date -u +%FT%TZ)" &&
    git push -qf "$REMOTE" data
  ) && rm -rf data/.git
}

alert() {
  curl -s -o /dev/null "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" || true
}

while :; do
  T0=$SECONDS
  echo "=== sweep $(date -u +%FT%TZ)"
  cargs=""; aargs="--if-due"
  if [ "$FIRST" = 1 ]; then
    [ "${DISCOVER:-}" = "true" ] && cargs="--discover"
    [ "${FORCE:-}" = "true" ] && aargs=""
    [ "${START_NOW:-}" = "true" ] && aargs="--start-now"
  fi
  # start the posting workflows when a slot is due (needs RADAR_DISPATCH_TOKEN; see trigger.py)
  python trigger.py --data data || echo "[loop] trigger failed"
  if python collect.py --data data $cargs; then
    python analyze.py --data data --send $aargs || echo "[loop] analyze failed (data still saved)"
    if save_data; then FAILS=0; else FAILS=$((FAILS + 1)); echo "[loop] save failed"; fi
  else
    FAILS=$((FAILS + 1)); echo "[loop] collect failed"
  fi
  if [ "$FAILS" -eq 3 ]; then
    alert "⚠️ Shorts Radar: 3 sweeps in a row failed. ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
  fi
  FIRST=0
  [ $((SECONDS + INTERVAL)) -ge "$END" ] && break
  WAIT=$((INTERVAL - (SECONDS - T0)))
  [ "$WAIT" -lt 60 ] && WAIT=60
  sleep "$WAIT"
done

# Only chain into a new run if this one actually lived (a run that dies in minutes would
# otherwise respawn itself in a tight loop); the 2-hourly cron backstop covers the rest.
if [ "$SECONDS" -ge 1200 ] && [ "$FAILS" -lt 3 ]; then touch .chain_ok; fi
echo "[loop] done after $((SECONDS / 60)) min"
