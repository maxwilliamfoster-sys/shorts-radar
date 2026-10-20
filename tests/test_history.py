import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import history

TABLE = """# Shorts Radar - 2026-10-18 12:40 UTC

### What the top quarter has in common

| feature | lift | in top 25% | in all | n |
|---|---|---|---|---|
| long_title(>=12w) | 1.54x | 6% | 4% | 44 |
| emoji | 0.95x | 48% | 51% | 626 |

### Length vs outlier score (median)
"""


class History(unittest.TestCase):
    def test_update_keeps_one_row_per_day_and_trims_old_days(self):
        h = {}
        start = date(2026, 8, 1)
        for d in range(70):
            history.update(h, (start + timedelta(days=d)).isoformat(), {"number": 1.2})
        history.update(h, "2026-10-09", {"number": 1.3})
        history.update(h, "2026-10-09", {"number": 1.4})          # same day twice: replaced
        self.assertEqual(h["2026-10-09"], {"number": 1.4})
        self.assertLessEqual(len(h), history.KEEP_DAYS)
        self.assertNotIn("2026-08-01", h)

    def test_stability_counts_days_above_the_bar_in_the_last_week(self):
        h = {}
        for i, lift in enumerate([1.3, 1.2, 1.0, 1.4, 1.5, 1.2, 1.3]):
            history.update(h, f"2026-10-{14 + i}", {"number": lift, "emoji": 0.9})
        history.update(h, "2026-10-01", {"number": 3.0})           # older than the window: ignored
        s = history.stability(h, "2026-10-20")
        self.assertEqual(s["number"], {"days_above": 6, "days_seen": 7})
        self.assertEqual(s["emoji"], {"days_above": 0, "days_seen": 7})

    def test_a_feature_missing_some_days_is_counted_as_not_seen(self):
        h = {}
        history.update(h, "2026-10-19", {"mate_in_n": 1.5})
        history.update(h, "2026-10-20", {"mate_in_n": 1.4, "number": 1.2})
        s = history.stability(h, "2026-10-20")
        self.assertEqual(s["mate_in_n"], {"days_above": 2, "days_seen": 2})
        self.assertEqual(s["number"], {"days_above": 1, "days_seen": 1})

    def test_is_stable_needs_most_of_a_week_not_two_lucky_days(self):
        self.assertTrue(history.is_stable({"days_above": 5, "days_seen": 7}))
        self.assertTrue(history.is_stable({"days_above": 5, "days_seen": 6}))
        self.assertFalse(history.is_stable({"days_above": 2, "days_seen": 2}))     # too few days to say
        self.assertFalse(history.is_stable({"days_above": 3, "days_seen": 7}))
        self.assertFalse(history.is_stable(None))

    def test_seed_reads_lifts_back_out_of_old_markdown_reports(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "2026-10-18.md"), "w", encoding="utf-8") as f:
                f.write(TABLE)
            with open(os.path.join(d, "latest.md"), "w", encoding="utf-8") as f:
                f.write(TABLE)
            h = history.seed_from_reports(d)
        self.assertEqual(h, {"2026-10-18": {"long_title(>=12w)": 1.54, "emoji": 0.95}})


if __name__ == "__main__":
    unittest.main()
