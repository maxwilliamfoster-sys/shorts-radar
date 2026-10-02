"""Simulated autopilot lifecycle: confirm -> start at 50% -> retire loser / promote winner /
hold when the channel gets no views. Run: py test_autopilot.py"""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autopilot, config

H = 3600
OWN = config.NICHES["chess"]["own_channel"]
T0 = 1_800_000_000


def res(lift=1.5):
    return [{"niche": "chess", "n_scored": 100,
             "feature_lift": [{"feature": "mate_in_n", "lift": lift, "n": 20, "share_top": 0.2, "share_all": 0.13}],
             "gaps": [{"feature": "mate_in_n", "own_share": 0.0, "share_top": 0.2, "lift": lift, "n": 20}]},
            {"niche": "reddit", "n_scored": 10, "feature_lift": [], "gaps": []}]


def empty():
    return {"videos": {}, "channels": {}}


def own_videos(treated_views, control_views, start):
    vids = {}
    for i, v in enumerate(treated_views + control_views):
        p = start + i * 8 * H
        title = "Can you find it? (Mate in 2)" if i < len(treated_views) else "Can you find it?"
        vids[f"v{i}"] = {"c": OWN, "n": "chess", "p": p, "t": title, "s": [[p + 47 * H, v], [p + 49 * H, v]]}
    return {"videos": vids, "channels": {}}


def started(d):
    autopilot.run(res(), empty(), [], d, T0)
    _, ap = autopilot.run(res(), empty(), [], d, T0 + 10 * H)
    assert not ap["active"]["chess"], "must wait CONFIRM_HOURS"
    _, ap = autopilot.run(res(), empty(), [], d, T0 + 21 * H)
    assert ap["active"]["chess"][0]["share"] == 0.5
    pub = json.load(open(os.path.join(d, "directives", "chess.json")))
    assert pub["directives"][0]["lever"] == "title_mate_in"
    return ap["active"]["chess"][0]["since"]


dirs = [tempfile.mkdtemp() for _ in range(3)]
try:
    since = started(dirs[0])
    st = own_videos([300] * 6, [1000] * 6, since + H)
    ch, ap = autopilot.run(res(), st, [], dirs[0], since + 29 * 24 * H)
    assert not ap["active"]["chess"] and "mate_in_n" in ap["retired"]["chess"], ch
    autopilot.run(res(), st, [], dirs[0], since + 31 * 24 * H)
    _, ap = autopilot.run(res(), st, [], dirs[0], since + 32 * 24 * H)
    assert not ap["active"]["chess"], "cooldown ignored"

    since = started(dirs[1])
    st = own_videos([2000] * 6, [1000] * 6, since + H)
    _, ap = autopilot.run(res(), st, [], dirs[1], since + 10 * 24 * H)
    assert ap["active"]["chess"][0]["share"] == 0.75

    since = started(dirs[2])
    st = own_videos([0] * 6, [3] * 6, since + H)
    ch, ap = autopilot.run(res(), st, [], dirs[2], since + 10 * 24 * H)
    assert ap["active"]["chess"] and not ch, ch
    # one sweep under the bar is tolerated; 6h+ under the bar restarts the 20h clock
    d4, d5 = tempfile.mkdtemp(), tempfile.mkdtemp()
    dirs += [d4, d5]
    autopilot.run(res(), empty(), [], d4, T0)
    autopilot.run(res(lift=1.1), empty(), [], d4, T0 + 5 * H)
    autopilot.run(res(), empty(), [], d4, T0 + 6 * H)
    _, ap = autopilot.run(res(), empty(), [], d4, T0 + 21 * H)
    assert ap["active"]["chess"], "brief dip should not reset"
    autopilot.run(res(), empty(), [], d5, T0)
    autopilot.run(res(lift=1.1), empty(), [], d5, T0 + 1 * H)
    autopilot.run(res(lift=1.1), empty(), [], d5, T0 + 8 * H)
    _, ap = autopilot.run(res(), empty(), [], d5, T0 + 21 * H)
    assert not ap["active"]["chess"], "long absence must reset the clock"
    print("ALL OK")
finally:
    for x in dirs:
        shutil.rmtree(x)
