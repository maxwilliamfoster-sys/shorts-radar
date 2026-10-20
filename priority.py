"""
Which of the chess bot's vetted A/B levers the radar's weekly read backs.

The radar never invents a test: it only names levers that already exist in the chess repo's
levers.json, so the nightly loop can start the best-supported one first. Pure function.
"""
import history

# radar feature -> chess lever (levers.json). Add a pair only after the lever exists and has
# passed a sample render in the chess repo.
LEVER_FOR_FEATURE = {
    "mate_in_n": "title_mate_tag",
}


def chess_priority(stability, now_iso, mapping=LEVER_FOR_FEATURE):
    found = []
    for feature, lever in mapping.items():
        s = stability.get(feature)
        if history.is_stable(s):
            found.append((s["days_above"] / s["days_seen"], lever, {"feature": feature, **s}))
    found.sort(key=lambda x: -x[0])
    return {"generated": now_iso, "levers": [l for _, l, _ in found],
            "evidence": {l: e for _, l, e in found}}
