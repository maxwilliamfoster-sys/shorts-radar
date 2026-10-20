import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import priority

STABLE = {"days_above": 7, "days_seen": 7}
FLUKE = {"days_above": 2, "days_seen": 7}


class ChessPriority(unittest.TestCase):
    def test_a_lever_is_prioritised_when_its_feature_held_most_of_the_week(self):
        out = priority.chess_priority({"mate_in_n": STABLE, "number": FLUKE}, now_iso="2026-10-27T07:00:00Z")
        self.assertEqual(out["levers"], ["title_mate_tag"])
        self.assertEqual(out["evidence"]["title_mate_tag"], {"feature": "mate_in_n", **STABLE})

    def test_a_one_day_fluke_prioritises_nothing(self):
        out = priority.chess_priority({"mate_in_n": FLUKE}, now_iso="2026-10-27T07:00:00Z")
        self.assertEqual(out["levers"], [])

    def test_features_with_no_lever_are_ignored(self):
        out = priority.chess_priority({"emoji": STABLE, "famous_player": STABLE}, now_iso="2026-10-27T07:00:00Z")
        self.assertEqual(out["levers"], [])

    def test_stamped_so_the_bot_can_ignore_a_dead_radar(self):
        out = priority.chess_priority({}, now_iso="2026-10-27T07:00:00Z")
        self.assertEqual(out["generated"], "2026-10-27T07:00:00Z")

    def test_strongest_evidence_goes_first(self):
        mapping = {"a": "lever_a", "b": "lever_b"}
        out = priority.chess_priority({"a": {"days_above": 5, "days_seen": 7}, "b": {"days_above": 7, "days_seen": 7}},
                                      now_iso="x", mapping=mapping)
        self.assertEqual(out["levers"], ["lever_b", "lever_a"])


if __name__ == "__main__":
    unittest.main()
