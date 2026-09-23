import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import badges as badge_rules


def iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class ScanCountBadgeTests(unittest.TestCase):
    def test_scan_count_thresholds(self):
        _, earned = badge_rules.evaluate_badges([{}] * 10, None)
        self.assertIn("scan_1", earned)
        self.assertIn("scan_10", earned)
        self.assertNotIn("scan_25", earned)

    def test_zero_scans_earns_no_scan_badge(self):
        _, earned = badge_rules.evaluate_badges([], None)
        self.assertNotIn("scan_1", earned)


class NetWorthBadgeTests(unittest.TestCase):
    def test_net_worth_threshold(self):
        _, earned = badge_rules.evaluate_badges([{"estimated_value": 60}], None)
        self.assertIn("worth_1", earned)
        self.assertIn("worth_50", earned)
        self.assertNotIn("worth_100", earned)

    def test_net_worth_sums_across_scans(self):
        scans = [{"estimated_value": 40}, {"estimated_value": 40}, {"estimated_value": None}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("worth_50", earned)
        self.assertNotIn("worth_100", earned)


class MembershipBadgeTests(unittest.TestCase):
    def test_no_created_at_earns_no_membership_badge(self):
        _, earned = badge_rules.evaluate_badges([], None)
        self.assertNotIn("mem_join", earned)
        self.assertNotIn("mem_7", earned)

    def test_membership_thresholds_from_real_profile_created_at(self):
        _, earned = badge_rules.evaluate_badges([], iso_days_ago(400))
        self.assertIn("mem_join", earned)
        self.assertIn("mem_7", earned)
        self.assertIn("mem_30", earned)
        self.assertIn("mem_180", earned)
        self.assertIn("mem_365", earned)
        self.assertNotIn("mem_730", earned)

    def test_brand_new_member_only_gets_mem_join(self):
        _, earned = badge_rules.evaluate_badges([], iso_days_ago(0))
        self.assertIn("mem_join", earned)
        self.assertNotIn("mem_7", earned)

    def test_zero_scans_can_still_have_membership_badges(self):
        """The exact scenario after a scans/api_usage reset: profiles are
        retained, so an account with zero scans is not guaranteed to have
        zero badges."""
        badge_count, earned = badge_rules.evaluate_badges([], iso_days_ago(400))
        self.assertGreater(badge_count, 0)
        self.assertIn("mem_365", earned)


class ForeignAndDenomTypeBadgeTests(unittest.TestCase):
    def test_foreign_badge(self):
        _, earned = badge_rules.evaluate_badges([{"is_foreign": True}], None)
        self.assertIn("type_foreign", earned)

    def test_domestic_scan_does_not_earn_foreign_badge(self):
        _, earned = badge_rules.evaluate_badges([{"is_foreign": False}], None)
        self.assertNotIn("type_foreign", earned)

    def test_denom_type_badges(self):
        scans = [{"denom_canonical": "dollar"}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("type_dollar", earned)
        self.assertNotIn("type_penny", earned)

    def test_foreign_5_cents_does_not_earn_penny_or_nickel(self):
        """Regression guard tying this to the corrected
        canonicalize_denomination behavior: a foreign 5-cent coin
        persists as the generic slug "5-cents", never "penny" or
        "nickel" - so it must not earn either badge here either."""
        scans = [{"denom_canonical": "5-cents", "is_foreign": True}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("type_penny", earned)
        self.assertNotIn("type_nickel", earned)
        self.assertIn("type_foreign", earned)


class StreakBadgeTests(unittest.TestCase):
    def test_penny_streak(self):
        scans = [{"denom_canonical": "penny"}] * 5
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("var_penny_streak", earned)

    def test_streak_broken_by_a_different_denom_does_not_count(self):
        scans = (
            [{"denom_canonical": "penny"}] * 4
            + [{"denom_canonical": "dime"}]
            + [{"denom_canonical": "penny"}] * 4
        )
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("var_penny_streak", earned)

    def test_quarter_streak_threshold_is_4(self):
        _, earned = badge_rules.evaluate_badges([{"denom_canonical": "quarter"}] * 4, None)
        self.assertIn("var_quarter_streak", earned)

    def test_wheat_streak_threshold_is_3(self):
        _, earned = badge_rules.evaluate_badges([{"denom_canonical": "wheat-penny"}] * 3, None)
        self.assertIn("var_wheat_streak", earned)

    def test_on_a_roll_any_denom_streak_of_5(self):
        _, earned = badge_rules.evaluate_badges([{"denom_canonical": "dollar"}] * 5, None)
        self.assertIn("var_on_a_roll", earned)

    def test_full_set_requires_all_four_denoms(self):
        scans = [{"denom_canonical": d} for d in ("penny", "nickel", "dime")]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("var_full_set", earned)
        scans.append({"denom_canonical": "quarter"})
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("var_full_set", earned)


class SeasonalDateBadgeTests(unittest.TestCase):
    def test_halloween_requires_5_scans_on_oct_31(self):
        scans = [{"local_date": "2026-10-31"}] * 5
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("season_halloween", earned)

    def test_halloween_not_earned_with_only_4(self):
        scans = [{"local_date": "2026-10-31"}] * 4
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("season_halloween", earned)

    def test_friday_the_13th(self):
        # 2024-09-13 is a real Friday the 13th.
        scans = [{"local_date": "2024-09-13"}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("season_friday13", earned)

    def test_the_13th_on_a_non_friday_does_not_count(self):
        # 2026-09-13 is a Sunday.
        scans = [{"local_date": "2026-09-13"}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("season_friday13", earned)

    def test_thanksgiving(self):
        # 2026-11-26 is the 4th Thursday of November 2026.
        scans = [{"local_date": "2026-11-26"}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("season_thanksgiving", earned)

    def test_christmas(self):
        scans = [{"local_date": "2026-12-25"}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("season_christmas", earned)

    def test_local_date_falls_back_to_scanned_at_date_portion(self):
        scans = [{"scanned_at": "2026-12-25T14:00:00+00:00"}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("season_christmas", earned)


class TimeOfDayBadgeTests(unittest.TestCase):
    def test_night_owl(self):
        _, earned = badge_rules.evaluate_badges([{"local_hour": 1}], None)
        self.assertIn("var_night_owl", earned)

    def test_night_owl_boundary_excludes_3am(self):
        _, earned = badge_rules.evaluate_badges([{"local_hour": 3}], None)
        self.assertNotIn("var_night_owl", earned)

    def test_early_bird(self):
        _, earned = badge_rules.evaluate_badges([{"local_hour": 5}], None)
        self.assertIn("var_early_bird", earned)

    def test_midday_scan_earns_neither(self):
        _, earned = badge_rules.evaluate_badges([{"local_hour": 13}], None)
        self.assertNotIn("var_night_owl", earned)
        self.assertNotIn("var_early_bird", earned)


class QuickfireBadgeTests(unittest.TestCase):
    def test_two_scans_within_60_seconds(self):
        scans = [
            {"scanned_at": "2026-09-13T10:00:00+00:00"},
            {"scanned_at": "2026-09-13T10:00:30+00:00"},
        ]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("var_quickfire", earned)

    def test_scans_over_a_minute_apart_do_not_count(self):
        scans = [
            {"scanned_at": "2026-09-13T10:00:00+00:00"},
            {"scanned_at": "2026-09-13T10:05:00+00:00"},
        ]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("var_quickfire", earned)


class OldSoulAndTimeMachineBadgeTests(unittest.TestCase):
    def test_old_soul(self):
        _, earned = badge_rules.evaluate_badges([{"year": 1943}], None)
        self.assertIn("var_old_soul", earned)

    def test_year_span_100_or_more(self):
        scans = [{"year": 1920}, {"year": 2020}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertIn("var_time_machine", earned)

    def test_year_span_under_100_does_not_count(self):
        scans = [{"year": 1990}, {"year": 2020}]
        _, earned = badge_rules.evaluate_badges(scans, None)
        self.assertNotIn("var_time_machine", earned)


class EvaluatorRobustnessTests(unittest.TestCase):
    def test_empty_scans_and_no_profile_earns_nothing(self):
        badge_count, earned = badge_rules.evaluate_badges([], None)
        self.assertEqual(badge_count, 0)
        self.assertEqual(earned, [])

    def test_none_scans_is_treated_as_empty(self):
        badge_count, earned = badge_rules.evaluate_badges(None, None)
        self.assertEqual(badge_count, 0)

    def test_badge_count_matches_length_of_earned_ids(self):
        scans = [{"estimated_value": 10}] * 15
        badge_count, earned = badge_rules.evaluate_badges(scans, iso_days_ago(10))
        self.assertEqual(badge_count, len(earned))
        self.assertEqual(len(earned), len(set(earned)))  # no duplicate ids


if __name__ == "__main__":
    unittest.main()
