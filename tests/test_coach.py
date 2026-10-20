import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach

NOW = 1792500000  # 2026-10-20

OWN = [
    "Win material — against Magnus Carlsen in a one-minute game. Can you?",
    "Can you match Magnus Carlsen? Win material.",
    "Magnus Carlsen didn't see this discovered attack. Will you?",
    "White to play: Magnus Carlsen found the mate in 2. Can you?",
    "Mate in 3 — against Magnus Carlsen in a one-minute game. Can you?",
    "Someone beat Hikaru Nakamura with this. Can you find the move?",
]


def result(**over):
    res = {
        "niche": "chess", "n_videos": 1903, "n_scored": 1230, "n_channels": 82,
        "breaking": [{"title": "Can u Explain❓", "channel": "Catur Talk", "views": 50536, "ratio": 9.2,
                      "age_h": 28, "duration": 12, "subs": 493000, "url": "https://youtube.com/shorts/aaa"}],
        "top_outliers": [{"title": "Magnus Carlsen TROLLS Pragg😂", "channel": "Convoy Chess", "views": 1184830,
                          "ratio": 33.1, "age_h": 174, "duration": 25, "subs": 809,
                          "url": "https://youtube.com/shorts/bbb"},
                         {"title": "The Safest King in the World 😂", "channel": "Catur Talk", "views": 208724,
                          "ratio": 24.8, "age_h": 412, "duration": 6, "subs": 493000,
                          "url": "https://youtube.com/shorts/ccc"}],
        "top_quartile_cut": 1.72,
        "feature_lift": [
            {"feature": "long_title(>=12w)", "lift": 1.54, "share_top": 0.06, "share_all": 0.04, "n": 44, "median_outlier": 1.2},
            {"feature": "number", "lift": 1.21, "share_top": 0.17, "share_all": 0.14, "n": 168, "median_outlier": 1.1},
            {"feature": "emoji", "lift": 0.95, "share_top": 0.48, "share_all": 0.51, "n": 626, "median_outlier": 1.0},
            {"feature": "posted_12-18utc", "lift": 0.74, "share_top": 0.30, "share_all": 0.40, "n": 491, "median_outlier": 0.9},
        ],
        "winning_words": [{"word": "against", "lift": 3.99, "in_winners": 12}],
        "duration_bands": {"≤20s": {"n": 882, "median_outlier": 1.01}, "21-45s": {"n": 267, "median_outlier": 1.01}},
        "you": {"videos": 6, "median_views": 1034, "median_v24": 946,
                "niche_small_channels_median_v24": 4959, "niche_small_channels_n": 855,
                "best": {"title": OWN[0], "views": 1545, "url": "https://youtube.com/shorts/own1"},
                "titles": OWN, "durations": [21, 22, 21, 23, 21, 20]},
        "winner_median_duration": 11,
        "stability": {"long_title(>=12w)": {"days_above": 6, "days_seen": 7},
                      "number": {"days_above": 2, "days_seen": 7}},
        "gaps": [{"feature": "posted_06-12utc", "lift": 1.21, "share_top": 0.35, "n": 353, "own_share": 0.08}],
        "hypotheses": [{"change": "Add a number hook", "why": "numbers lift 1.21",
                        "evidence": ["a", "b"], "how_to_test": "A/B 8 vs 8"}],
    }
    res.update(over)
    return res


class BuildPrompt(unittest.TestCase):
    def test_is_a_self_contained_ask_for_the_chess_bot(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("@CandidateMoves", p)
        self.assertIn("@@REPO@@", p)
        self.assertNotIn("maxwi", p)                    # public repo: no local paths
        self.assertIn("chess_puzzle_automation.md", p)
        self.assertIn("2026-10-20", p)

    def test_carries_the_gathered_evidence(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("946", p)                         # own 24h median
        self.assertIn("4,959", p)                       # small-competitor median
        self.assertIn("Can u Explain", p)               # breaking now
        self.assertIn("https://youtube.com/shorts/bbb", p)
        self.assertIn("long_title(>=12w)", p)
        self.assertIn("1230", p)                        # sample size is stated
        self.assertIn("Add a number hook", p)           # radar hypotheses

    def test_only_winning_features_are_listed_as_levers(self):
        p = coach.build_prompt(result(), NOW)
        lever = p.split("What over-indexes")[1].split("\n\n")[0]
        self.assertIn("number", lever)
        self.assertNotIn("emoji", lever)

    def test_flags_when_every_own_title_repeats_one_formula(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("Magnus Carlsen", p)
        self.assertRegex(p, r"5 of 6")                  # five of six titles name Magnus Carlsen

    def test_compares_own_length_with_what_winners_run(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("21s", p)                         # our median
        self.assertIn("11s", p)                         # winners' median

    def test_keeps_the_pipelines_hard_rules(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("£0", p)
        self.assertIn("narration", p.lower())
        self.assertIn("A/B", p)
        self.assertIn("failing test first", p)

    def test_warns_about_small_samples_and_copying(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("correlation", p.lower())
        self.assertIn("do not copy", p.lower())

    def test_thin_data_says_so_instead_of_inventing_levers(self):
        p = coach.build_prompt(result(n_scored=12, feature_lift=[], winning_words=[], top_outliers=[],
                                      breaking=[], gaps=[], hypotheses=[], duration_bands={},
                                      winner_median_duration=None), NOW)
        self.assertIn("not enough", p.lower())
        self.assertNotIn("What over-indexes", p)

    def test_separates_patterns_that_held_all_week_from_one_day_flukes(self):
        p = coach.build_prompt(result(), NOW)
        held = p.split("Held up most of the week")[1].split("\n\n")[0]
        self.assertIn("long_title(>=12w)", held)
        self.assertIn("6 of 7", held)
        self.assertNotIn("number", held)
        self.assertIn("2 of 7", p.split("What over-indexes")[1].split("\n\n")[0])

    def test_when_nothing_held_it_says_not_to_start_tests(self):
        p = coach.build_prompt(result(stability={"number": {"days_above": 2, "days_seen": 7}}), NOW)
        self.assertNotIn("Held up most of the week", p)
        self.assertIn("No pattern has held", p)
        self.assertIn("do not start a new test", p.lower())

    def test_asks_claude_to_pick_the_weeks_ab_tests_without_touching_running_ones(self):
        p = coach.build_prompt(result(), NOW)
        self.assertIn("EXPERIMENTS.md", p)
        self.assertIn("experiments.py", p)
        self.assertIn("running", p.lower())
        self.assertIn("stay rate", p.lower())
        self.assertIn("up to 2 NEW levers", p)
        self.assertIn("levers.json", p)

    def test_missing_own_data_does_not_crash(self):
        p = coach.build_prompt(result(you={"videos": 0, "titles": [], "durations": []}), NOW)
        self.assertIn("@CandidateMoves", p)


if __name__ == "__main__":
    unittest.main()
