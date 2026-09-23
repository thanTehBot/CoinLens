import json
import os
import sys
import unittest
from unittest import mock

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import app as coinlens_app


def identification(**overrides):
    base = {
        "identifiable": True, "country": "Canada", "denomination": "1 dollar",
        "year": "2016", "mint_mark": None, "estimated_grade": "AU-50",
    }
    base.update(overrides)
    return base


class ScoreBreakdownTests(unittest.TestCase):
    def test_country_and_denomination_match_score_higher_than_country_alone(self):
        right_denomination = {
            "id": 1, "title": "1 Dollar - Elizabeth II (Loon)",
            "issuer": {"name": "Canada"}, "min_year": 1987, "max_year": 2016,
        }
        wrong_denomination = {
            "id": 2, "title": "1 Cent - Victoria",
            "issuer": {"name": "Canada"}, "min_year": 1858, "max_year": 1901,
        }

        right_score, right_breakdown = coinlens_app._score_numista_candidate_breakdown(identification(), right_denomination)
        wrong_score, wrong_breakdown = coinlens_app._score_numista_candidate_breakdown(identification(), wrong_denomination)

        self.assertGreater(right_score, wrong_score)
        self.assertIn("denomination_in_title", right_breakdown)
        self.assertIn("year_in_type_range", right_breakdown)
        self.assertNotIn("denomination_in_title", wrong_breakdown)

    def test_wrong_country_candidate_gets_no_country_credit(self):
        """Reproduces the real 'Canada 1 dollar' search: an Australian '1
        Dollar' type matches the denomination text but must not get the
        country bonus just because 'dollar' is a common word."""
        australian = {
            "id": 3, "title": "1 Dollar - Elizabeth II",
            "issuer": {"name": "Australia"}, "min_year": 2010, "max_year": 2010,
        }
        score, breakdown = coinlens_app._score_numista_candidate_breakdown(identification(), australian)
        self.assertNotIn("country_issuer_match", breakdown)
        self.assertIn("denomination_in_title", breakdown)
        self.assertEqual(score, 2)


class DenominationNormalizationTests(unittest.TestCase):
    """Real production case: the AI said "Twenty pence" while Numista
    titles say "20 Pence" - a plain substring check never matched, so
    2/20/50 Pence candidates all scored identically on denomination."""

    def test_twenty_pence_matches_20_pence(self):
        self.assertEqual(
            coinlens_app.normalize_numista_denomination("Twenty pence"),
            coinlens_app.normalize_numista_denomination("20 Pence"),
        )

    def test_twenty_pence_does_not_match_2_pence(self):
        self.assertNotEqual(
            coinlens_app.normalize_numista_denomination("Twenty pence"),
            coinlens_app.normalize_numista_denomination("2 Pence"),
        )

    def test_twenty_pence_does_not_match_50_pence(self):
        self.assertNotEqual(
            coinlens_app.normalize_numista_denomination("Twenty pence"),
            coinlens_app.normalize_numista_denomination("50 Pence"),
        )

    def test_five_cents_matches_5_cents(self):
        self.assertEqual(
            coinlens_app.normalize_numista_denomination("Five cents"),
            coinlens_app.normalize_numista_denomination("5 Cents"),
        )

    def test_two_dollars_matches_2_dollars(self):
        self.assertEqual(
            coinlens_app.normalize_numista_denomination("Two dollars"),
            coinlens_app.normalize_numista_denomination("2 dollars"),
        )

    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(
            coinlens_app.normalize_numista_denomination("  TWENTY   Pence  "),
            coinlens_app.normalize_numista_denomination("20 pence"),
        )

    def test_extracts_denomination_from_a_full_numista_title(self):
        self.assertEqual(
            coinlens_app._numista_title_denomination("20 Pence - Elizabeth II (4th portrait; Royal Shield)"),
            coinlens_app.normalize_numista_denomination("Twenty pence"),
        )
        self.assertNotEqual(
            coinlens_app._numista_title_denomination("2 Pence - Elizabeth II"),
            coinlens_app.normalize_numista_denomination("Twenty pence"),
        )

    # -- Real production case: a Hong Kong $2 scan showed a title with no
    # " - " series separator at all - just a trailing parenthetical
    # qualifier directly after the denomination ("2 Dollars (Special
    # Administration Region)") - whose words leaked into the normalized
    # denomination and broke the match against the AI's plain "2 dollars".

    def test_plain_title_matches_ai_denomination(self):
        self.assertEqual(
            coinlens_app._numista_title_denomination("2 Dollars"),
            coinlens_app.normalize_numista_denomination("2 dollars"),
        )

    def test_trailing_parenthetical_qualifier_does_not_break_the_match(self):
        self.assertEqual(
            coinlens_app._numista_title_denomination("2 Dollars (Special Administration Region)"),
            coinlens_app.normalize_numista_denomination("2 dollars"),
        )

    def test_trailing_parenthetical_qualifier_does_not_cause_a_false_match(self):
        self.assertNotEqual(
            coinlens_app._numista_title_denomination("20 Cents (Special Administration Region)"),
            coinlens_app.normalize_numista_denomination("2 dollars"),
        )

    def test_trailing_parenthetical_qualifier_with_pence(self):
        self.assertEqual(
            coinlens_app._numista_title_denomination("20 Pence (Royal Shield)"),
            coinlens_app.normalize_numista_denomination("20 pence"),
        )
        self.assertEqual(
            coinlens_app._numista_title_denomination("20 Pence (Royal Shield)"),
            coinlens_app.normalize_numista_denomination("Twenty pence"),
        )

    def test_20_dollars_still_does_not_match_2_dollars(self):
        self.assertNotEqual(
            coinlens_app._numista_title_denomination("20 Dollars"),
            coinlens_app.normalize_numista_denomination("2 dollars"),
        )


class IssueMatchingTests(unittest.TestCase):
    def test_issue_matches_exact_year(self):
        self.assertTrue(coinlens_app._issue_matches_year({"year": 2012}, "2012"))

    def test_issue_matches_year_range(self):
        self.assertTrue(coinlens_app._issue_matches_year({"min_year": 2010, "max_year": 2015}, "2012"))

    def test_issue_does_not_match_other_year(self):
        self.assertFalse(coinlens_app._issue_matches_year({"year": 2011}, "2012"))

    def test_non_numeric_year_never_matches(self):
        self.assertFalse(coinlens_app._issue_matches_year({"year": 2012}, "Unknown"))

    def test_select_issue_for_year_picks_the_matching_one(self):
        issues = [{"id": "i1", "year": 2011}, {"id": "i2", "year": 2012}, {"id": "i3", "year": 2013}]
        selected, reason = coinlens_app._select_issue_for_year(identification(year="2012"), issues)
        self.assertEqual(selected["id"], "i2")
        self.assertIsNone(reason)

    def test_select_issue_for_year_returns_none_when_no_year_matches(self):
        issues = [{"id": "i1", "year": 2011}, {"id": "i3", "year": 2013}]
        selected, reason = coinlens_app._select_issue_for_year(identification(year="2012"), issues)
        self.assertIsNone(selected)
        self.assertEqual(reason, "no issue matches year")

    def test_select_issue_disambiguates_by_mint_mark_when_tied_on_year(self):
        issues = [
            {"id": "philly", "year": 2012, "mint_letter": "P"},
            {"id": "denver", "year": 2012, "mint_letter": "D"},
        ]
        selected, reason = coinlens_app._select_issue_for_year(identification(year="2012", mint_mark="D"), issues)
        self.assertEqual(selected["id"], "denver")
        self.assertIsNone(reason)

    def test_select_issue_with_unresolvable_mint_tie_and_no_special_marker_is_ambiguous(self):
        """Previously this blindly picked the first year-match when no
        mint mark was available - exactly the kind of silent guess this
        matching pipeline is meant to avoid. Two indistinguishable ordinary
        issues (no special comment on either) must now return None, with a
        reason distinct from "no issue matches year" (the year DID match)."""
        issues = [
            {"id": "philly", "year": 2012, "mint_letter": "P"},
            {"id": "denver", "year": 2012, "mint_letter": "D"},
        ]
        selected, reason = coinlens_app._select_issue_for_year(identification(year="2012", mint_mark=None), issues)
        self.assertIsNone(selected)
        self.assertEqual(reason, "year matched but multiple ordinary issues remain indistinguishable")

    # -- Real production case: type 5628 (UK 20p) had three 2012 issues -
    # ordinary circulation, "BU", and "Proof". Exact live response shape,
    # including fields (is_dated/gregorian_year) not exercised by the
    # simplified issue dicts used elsewhere in this file. -----------------

    UK_20P_2012_ISSUES = [
        {"id": 144284, "is_dated": True, "year": 2012, "gregorian_year": 2012, "mintage": 69650030},
        {"id": 520198, "is_dated": True, "year": 2012, "gregorian_year": 2012, "mintage": 77725, "comment": "BU"},
        {"id": 180337, "is_dated": True, "year": 2012, "gregorian_year": 2012, "mintage": 26552, "comment": "Proof"},
    ]

    def test_ordinary_grade_prefers_the_plain_circulation_issue_over_bu_and_proof(self):
        """The exact live regression: AI says VF-20/ordinary circulating
        coin: issue 144284 (no comment) must win over 520198 (BU) and
        180337 (Proof), using the real response shape verbatim."""
        ident = identification(
            country="United Kingdom", denomination="20 pence", year="2012", estimated_grade="VF-20",
            description="ordinary circulating coin, normal wear/scratches",
        )
        selected, reason = coinlens_app._select_issue_for_year(ident, self.UK_20P_2012_ISSUES, type_id=5628)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], 144284)
        self.assertIsNone(reason)

    def test_explicit_proof_identification_does_not_blindly_select_ordinary_issue(self):
        ident = identification(
            country="United Kingdom", denomination="Twenty pence", year="2012",
            description="This appears to be a proof strike with mirrored fields.",
        )
        selected, reason = coinlens_app._select_issue_for_year(ident, self.UK_20P_2012_ISSUES)
        # Must not silently land on the ordinary circulation issue just
        # because it's one of the tied candidates.
        self.assertNotEqual((selected or {}).get("id"), 144284)
        self.assertIsNone(selected)
        self.assertEqual(reason, "year matched but AI indicated a special issue and multiple candidates remain ambiguous")

    def test_multiple_indistinguishable_ordinary_issues_return_none(self):
        issues = [
            {"id": "issue-a", "year": 2012},
            {"id": "issue-b", "year": 2012},
        ]
        ident = identification(country="United Kingdom", denomination="Twenty pence", year="2012")
        selected, reason = coinlens_app._select_issue_for_year(ident, issues)
        self.assertIsNone(selected)
        self.assertEqual(reason, "year matched but multiple ordinary issues remain indistinguishable")

    def test_issue_evaluation_is_logged_for_every_year_matching_issue(self):
        with self.assertLogs(coinlens_app.app.logger, level="INFO") as logs:
            coinlens_app._select_issue_for_year(
                identification(country="United Kingdom", denomination="20 pence", year="2012", estimated_grade="VF-20"),
                self.UK_20P_2012_ISSUES, type_id=5628,
            )
        eval_lines = [line for line in logs.output if "issue evaluation" in line]
        self.assertEqual(len(eval_lines), 3)
        self.assertTrue(any("issue_id=144284" in line and "decision=accepted" in line for line in eval_lines))
        self.assertTrue(any("issue_id=520198" in line and "rejected" in line for line in eval_lines))
        self.assertTrue(any("issue_id=180337" in line and "rejected" in line for line in eval_lines))

    # -- Real production case: 2016 Canada 5 cents, type 395. "Uncirculated"
    # was missing from the special-keyword set, so issue 853959 tied with
    # the genuinely ordinary 284842 and the whole type got rejected as
    # ambiguous even though only one issue was actually ordinary. ---------

    CANADA_5C_2016_ISSUES = [
        {"id": 284842, "year": 2016},
        {"id": 311832, "year": 2016, "comment": "Specimen"},
        {"id": 853959, "year": 2016, "comment": "Uncirculated"},
        {"id": 1104358, "year": 2016, "comment": "Proof"},
    ]

    def test_canada_2016_5c_regression_selects_ordinary_issue_284842(self):
        """The AI's grade was AU-55 (About Uncirculated - a condition
        grade) - this must never be confused with the Numista issue
        comment "Uncirculated" (a mint/collector product) and must not
        stop 284842 (the genuinely ordinary issue, blank comment) from
        winning."""
        ident = identification(
            country="Canada", denomination="5 cents", year="2016",
            estimated_grade="AU-55 (visual estimate; not professionally certified)",
            description="standard circulation design",
        )
        selected, reason = coinlens_app._select_issue_for_year(ident, self.CANADA_5C_2016_ISSUES, type_id=395)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], 284842)
        self.assertIsNone(reason)

    def test_looks_special_issue_matches_whole_words_only(self):
        self.assertTrue(coinlens_app._looks_special_issue({"comment": "Proof"}))
        self.assertTrue(coinlens_app._looks_special_issue({"comment": "BU"}))
        # A Numista issue *comment* of "Uncirculated" denotes a specific
        # mint/collector product (special), not the AI's own "AU"
        # (About Uncirculated) condition grade - those are unrelated
        # concepts, and this comment must be treated as special whenever
        # it appears, "About" or not.
        self.assertTrue(coinlens_app._looks_special_issue({"comment": "About uncirculated"}))
        self.assertFalse(coinlens_app._looks_special_issue({}))

    def test_looks_special_issue_required_keyword_table(self):
        """The exact table this task requires classifiers to recognize."""
        special_comments = [
            "Proof", "Prooflike", "Proof-like", "Specimen",
            "Uncirculated", "uncirculated", "Brilliant uncirculated",
            "Brilliant Uncirculated", "BU", "Special Edition", "Mint Set", "Proof Set",
        ]
        for comment in special_comments:
            with self.subTest(comment=comment):
                self.assertTrue(coinlens_app._looks_special_issue({"comment": comment}))
        self.assertFalse(coinlens_app._looks_special_issue({"comment": ""}))


class ResolveTypeAndIssueTests(unittest.TestCase):
    """Core regression coverage for the real production bug: title/country
    scoring alone picked a wrong-era 'Cent' candidate over the correct
    'Dollar' type for a real Canada scan. These tests construct a candidate
    pair where the WRONG one deliberately outscores the RIGHT one (as
    happened for real, since Numista's title omits the leading '1' for the
    correct type) and assert the issue-year check still finds the correct
    one instead of trusting the raw score."""

    def test_prefers_issue_confirmed_candidate_over_a_higher_scored_wrong_one(self):
        # Deliberately scores higher than the correct candidate below (5 vs
        # 3) by having a coincidentally-overlapping year range - simulating
        # a scoring/title-format weakness, not a contrived edge case.
        higher_scored_wrong_era = {
            "id": 1, "title": "1 Cent - Victoria",
            "issuer": {"name": "Canada"}, "min_year": 2010, "max_year": 2020,
        }
        # Numista's real title for this type omits the leading "1" (just
        # "Dollar", not "1 Dollar"), so our denomination substring check
        # misses it - this is the correct type, but scores lower.
        lower_scored_right_coin = {
            "id": 999, "title": "Dollar - Elizabeth II (Loon)",
            "issuer": {"name": "Canada"}, "min_year": 1987, "max_year": None,
        }

        def fake_issues(type_id):
            if type_id == 999:
                return [{"id": "iss-2016", "year": 2016}]
            return [{"id": "iss-2010", "year": 2010}]

        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=fake_issues):
            best, issue = coinlens_app.resolve_numista_type_and_issue(
                identification(), [higher_scored_wrong_era, lower_scored_right_coin]
            )

        self.assertEqual(best["id"], 999)
        self.assertEqual(issue["id"], "iss-2016")

    def test_returns_none_when_no_inspected_candidate_has_a_matching_issue(self):
        candidates = [{
            "id": 1, "title": "1 Dollar - Elizabeth II",
            "issuer": {"name": "Canada"}, "min_year": 1987, "max_year": 2020,
        }]
        with mock.patch.object(coinlens_app, "fetch_numista_issues", return_value=[{"id": "iss-1990", "year": 1990}]):
            best, issue = coinlens_app.resolve_numista_type_and_issue(identification(), candidates)
        self.assertIsNone(best)
        self.assertIsNone(issue)

    def test_does_not_inspect_more_than_the_configured_candidate_cap(self):
        candidates = [
            {
                "id": i, "title": "1 Dollar - Elizabeth II",
                "issuer": {"name": "Canada"}, "min_year": 1987, "max_year": 2020,
            }
            for i in range(10)
        ]
        with mock.patch.object(coinlens_app, "fetch_numista_issues", return_value=[]) as mock_issues:
            coinlens_app.resolve_numista_type_and_issue(identification(), candidates)
        self.assertLessEqual(mock_issues.call_count, coinlens_app.NUMISTA_MATCH_CANDIDATES_TO_INSPECT)

    def test_skips_low_scoring_candidates_without_an_issues_call(self):
        irrelevant = {
            "id": 1, "title": "Souvenir Token",
            "issuer": {"name": "France"}, "min_year": 1990, "max_year": 1990,
        }
        with mock.patch.object(coinlens_app, "fetch_numista_issues") as mock_issues:
            best, issue = coinlens_app.resolve_numista_type_and_issue(identification(), [irrelevant])
        mock_issues.assert_not_called()
        self.assertIsNone(best)

    def test_multiple_candidates_with_matching_issues_return_unavailable_not_a_guess(self):
        """Real production scenario: several plausible UK 20p-family types
        could each turn out to have an issue for the identified year. Since
        we can't safely tell them apart, this must report unavailable
        rather than silently picking one (e.g. by score)."""
        candidate_a = {
            "id": 1, "title": "20 Pence - Elizabeth II (Type A)",
            "issuer": {"name": "United Kingdom"}, "min_year": 2008, "max_year": 2015,
        }
        candidate_b = {
            "id": 2, "title": "20 Pence - Elizabeth II (Type B)",
            "issuer": {"name": "United Kingdom"}, "min_year": 2008, "max_year": 2015,
        }

        def fake_issues(type_id):
            return [{"id": f"iss-{type_id}-2012", "year": 2012}]

        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=fake_issues):
            best, issue = coinlens_app.resolve_numista_type_and_issue(
                identification(country="United Kingdom", denomination="20 pence", year="2012"),
                [candidate_a, candidate_b],
            )
        self.assertIsNone(best)
        self.assertIsNone(issue)


class VariantDisambiguationTests(unittest.TestCase):
    """Real production case: a 2012 UK 20 pence scan returned three
    candidates that all had a valid 2012 issue - a standard circulation
    type, a non-circulating 1/10oz fine-silver type, and a silver-proof
    variant. The year/issue gate correctly refused to guess. These cover
    preferring the ordinary circulation type using only object_type/title
    fields Numista already returns - never weakening the year/issue gate
    itself, and never guessing when the AI actually flagged something
    special or when circulation candidates themselves remain tied."""

    UK_20P_CANDIDATES = [
        {
            "id": 29106, "title": "20 Pence - Elizabeth II (4th portrait; 1/10 oz Fine Silver)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"id": 3, "name": "Non-circulating coins"},
        },
        {
            "id": 5628, "title": "20 Pence - Elizabeth II (4th portrait; Royal Shield)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"id": 1, "name": "Standard circulation coins"},
        },
        {
            "id": 208022, "title": "20 Pence - Elizabeth II (4th portrait; Royal Shield, Silver Proof)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"id": 3, "name": "Non-circulating coins"},
        },
    ]

    def _all_candidates_have_a_2012_issue(self, type_id):
        return [{"id": f"iss-{type_id}-2012", "year": 2012}]

    def test_uk_2012_20p_regression_with_ai_wording_twenty_pence_outranks_2_pence(self):
        """The real bug: the AI said "Twenty pence" (not "20 pence"), so
        the old substring-based scorer never matched any candidate's
        denomination, leaving 2p/20p/50p tied on country+year alone. Type
        5628 (20 Pence) must now clearly outscore a 2 Pence type (4039)
        before variant resolution even runs."""
        two_pence = {
            "id": 4039, "title": "2 Pence - Elizabeth II (2nd portrait)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Standard circulation coins"},
        }
        twenty_pence = {
            "id": 5628, "title": "20 Pence - Elizabeth II (4th portrait; Royal Shield)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Standard circulation coins"},
        }
        fifty_pence = {
            "id": 9001, "title": "50 Pence - Elizabeth II (3rd portrait)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Standard circulation coins"},
        }

        two_pence_score, _ = coinlens_app._score_numista_candidate_breakdown(
            identification(country="United Kingdom", denomination="Twenty pence", year="2012"), two_pence)
        twenty_pence_score, _ = coinlens_app._score_numista_candidate_breakdown(
            identification(country="United Kingdom", denomination="Twenty pence", year="2012"), twenty_pence)
        fifty_pence_score, _ = coinlens_app._score_numista_candidate_breakdown(
            identification(country="United Kingdom", denomination="Twenty pence", year="2012"), fifty_pence)

        self.assertGreater(twenty_pence_score, two_pence_score)
        self.assertGreater(twenty_pence_score, fifty_pence_score)

        ident = identification(country="United Kingdom", denomination="Twenty pence", year="2012", estimated_grade="VF-25")
        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=self._all_candidates_have_a_2012_issue):
            best, issue = coinlens_app.resolve_numista_type_and_issue(ident, [two_pence, twenty_pence, fifty_pence])

        self.assertIsNotNone(best)
        self.assertEqual(best["id"], 5628)
        self.assertEqual(issue["id"], "iss-5628-2012")

    def test_uk_2012_20p_regression_prefers_standard_circulation_type_5628(self):
        ident = identification(
            country="United Kingdom", denomination="20 pence", year="2012",
            estimated_grade="VF-30", description="An ordinary seven-sided circulating coin.",
        )
        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=self._all_candidates_have_a_2012_issue):
            best, issue = coinlens_app.resolve_numista_type_and_issue(ident, self.UK_20P_CANDIDATES)

        self.assertIsNotNone(best)
        self.assertEqual(best["id"], 5628)
        self.assertEqual(issue["id"], "iss-5628-2012")

    def test_ai_explicitly_saying_silver_proof_does_not_auto_select_circulation(self):
        ident = identification(
            country="United Kingdom", denomination="20 pence", year="2012",
            description="This looks like a silver proof striking with mirrored fields.",
        )
        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=self._all_candidates_have_a_2012_issue):
            best, issue = coinlens_app.resolve_numista_type_and_issue(ident, self.UK_20P_CANDIDATES)

        # Must NOT silently land on the standard-circulation type just
        # because it's one of the tied candidates.
        self.assertNotEqual((best or {}).get("id"), 5628)
        self.assertIsNone(best)
        self.assertIsNone(issue)

    def test_two_standard_circulation_candidates_still_tied_remain_unavailable(self):
        candidate_a = {
            "id": 1, "title": "20 Pence - Elizabeth II (Type A)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Standard circulation coins"},
        }
        candidate_b = {
            "id": 2, "title": "20 Pence - Elizabeth II (Type B)",
            "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Standard circulation coins"},
        }
        ident = identification(country="United Kingdom", denomination="20 pence", year="2012")
        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=self._all_candidates_have_a_2012_issue):
            best, issue = coinlens_app.resolve_numista_type_and_issue(ident, [candidate_a, candidate_b])

        self.assertIsNone(best)
        self.assertIsNone(issue)

    def test_wrong_year_rejection_is_unaffected_by_variant_disambiguation(self):
        """The standard-circulation type itself has no 2012 issue (only the
        proof variant does) - it must still be rejected by the year check,
        not force-selected just because it's "the ordinary one"."""
        candidates = [
            {
                "id": 5628, "title": "20 Pence - Elizabeth II (4th portrait; Royal Shield)",
                "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Standard circulation coins"},
            },
            {
                "id": 208022, "title": "20 Pence - Elizabeth II (4th portrait; Royal Shield, Silver Proof)",
                "issuer": {"name": "United Kingdom"}, "object_type": {"name": "Non-circulating coins"},
            },
        ]

        def fake_issues(type_id):
            if type_id == 5628:
                return [{"id": "iss-5628-2015", "year": 2015}]  # no 2012 issue
            return [{"id": "iss-208022-2012", "year": 2012}]

        ident = identification(country="United Kingdom", denomination="20 pence", year="2012")
        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=fake_issues):
            best, issue = coinlens_app.resolve_numista_type_and_issue(ident, candidates)

        self.assertEqual(best["id"], 208022)
        self.assertEqual(issue["id"], "iss-208022-2012")

    def test_looks_special_or_proof_classifies_by_object_type(self):
        self.assertTrue(coinlens_app.looks_special_or_proof({"title": "20 Pence", "object_type": {"name": "Non-circulating coins"}}))
        self.assertFalse(coinlens_app.looks_special_or_proof({"title": "20 Pence", "object_type": {"name": "Standard circulation coins"}}))

    def test_looks_special_or_proof_classifies_by_title_keywords(self):
        self.assertTrue(coinlens_app.looks_special_or_proof({"title": "1 Dollar - Proof"}))
        self.assertTrue(coinlens_app.looks_special_or_proof({"title": "20 Pence (1/4 oz Fine Gold)"}))
        # A bare metal word alone (no object_type given) is not enough -
        # plenty of ordinary historical circulation coins are gold/silver.
        self.assertFalse(coinlens_app.looks_special_or_proof({"title": "Sixpence - George VI (Silver)"}))

    def test_ai_indicates_special_variant_reads_description(self):
        self.assertTrue(coinlens_app.ai_indicates_special_variant(identification(description="A gold commemorative issue.")))
        self.assertTrue(coinlens_app.ai_indicates_special_variant(identification(special_notes="Appears to be a proof strike.")))
        self.assertFalse(coinlens_app.ai_indicates_special_variant(identification(description="An ordinary circulating coin.")))

    def test_hong_kong_2_dollar_regression_both_survive_denomination_then_circulation_wins(self):
        """Real production case: candidate 5280's title has no " - "
        series separator, just a trailing "(Special Administration
        Region)" qualifier directly after the denomination - previously
        this broke denomination matching and dropped 5280 outright. Both
        1582 and 5280 are genuinely "2 dollars" and must both survive the
        denomination check; only then does the (unrelated,
        already-existing) type-level variant step prefer the standard
        circulation type over the commemorative one."""
        wrong_denomination = {
            "id": 5276, "title": "20 Cents (Special Administration Region)",
            "issuer": {"name": "Hong Kong"}, "object_type": {"name": "Standard circulation coins"},
        }
        standard_circulation = {
            "id": 1582, "title": "2 Dollars",
            "issuer": {"name": "Hong Kong"}, "object_type": {"name": "Standard circulation coins"},
        }
        commemorative = {
            "id": 5280, "title": "2 Dollars (Special Administration Region)",
            "issuer": {"name": "Hong Kong"}, "object_type": {"name": "Circulating commemorative coins"},
        }

        # Denomination check alone (before any issue lookup): 5276 must be
        # excluded, 1582 and 5280 must both survive.
        ai_denomination = coinlens_app.normalize_numista_denomination("2 dollars")
        self.assertNotEqual(coinlens_app._numista_title_denomination(wrong_denomination["title"]), ai_denomination)
        self.assertEqual(coinlens_app._numista_title_denomination(standard_circulation["title"]), ai_denomination)
        self.assertEqual(coinlens_app._numista_title_denomination(commemorative["title"]), ai_denomination)

        def fake_issues(type_id):
            return [{"id": f"iss-{type_id}-1997", "year": 1997}]

        ident = identification(
            country="Hong Kong", denomination="2 dollars", year="1997",
            description="An ordinary circulating coin.",
        )
        with mock.patch.object(coinlens_app, "fetch_numista_issues", side_effect=fake_issues):
            best, issue = coinlens_app.resolve_numista_type_and_issue(
                ident, [wrong_denomination, standard_circulation, commemorative],
            )

        self.assertIsNotNone(best)
        self.assertEqual(best["id"], 1582)
        self.assertEqual(issue["id"], "iss-1582-1997")


class GradeNormalizationTests(unittest.TestCase):
    """Real production case: the AI's raw grade string ("F-12 (visual
    estimate)") was compared for exact equality against Numista's own
    short grade codes ("f", "vf", ...), which never matched, so every real
    scan fell through to the crude "nearest available" (middle-indexed
    priced entry) fallback - here it happened to return the same price as
    the correct grade, masking the bug; that won't always be true."""

    def test_common_numeric_grade_forms(self):
        cases = {
            "G-4": "g", "VG-8": "vg",
            "F-12": "f", "F-15": "f",
            "VF-20": "vf", "VF-25": "vf", "VF-30": "vf", "VF-35": "vf",
            "XF-40": "xf", "XF-45": "xf", "EF-40": "xf", "EF-45": "xf",
            "AU-50": "au", "AU-53": "au", "AU-55": "au", "AU-58": "au",
            "MS-60+": "unc", "UNC": "unc", "MS-63": "unc",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(coinlens_app.normalize_numista_grade(raw), expected)

    def test_ignores_explanatory_parenthetical_suffixes(self):
        self.assertEqual(coinlens_app.normalize_numista_grade("F-12 (visual estimate)"), "f")
        self.assertEqual(
            coinlens_app.normalize_numista_grade("VF-25 (visual estimate; not professionally certified)"), "vf",
        )

    def test_already_short_codes_are_a_safe_no_op(self):
        for code in ("g", "vg", "f", "vf", "xf", "au", "unc"):
            self.assertEqual(coinlens_app.normalize_numista_grade(code), code)

    def test_blank_grade_normalizes_to_empty_string(self):
        self.assertEqual(coinlens_app.normalize_numista_grade(None), "")
        self.assertEqual(coinlens_app.normalize_numista_grade(""), "")


class FetchNumistaPriceTests(unittest.TestCase):
    def test_requests_the_issue_scoped_price_endpoint(self):
        """Numista v3 prices a specific issue, not a whole type - regression
        guard for the old (wrong) /types/{id}/prices path."""
        coinlens_app.NUMISTA_API_KEY = "test-key"
        response = mock.Mock(status_code=200, text='{"prices": []}')
        response.json.return_value = {"prices": []}
        with mock.patch.object(coinlens_app.requests, "get", return_value=response) as mock_get:
            coinlens_app.fetch_numista_price(999, "iss-2016", "AU-50")
        called_url = mock_get.call_args.args[0]
        self.assertEqual(called_url, f"{coinlens_app.NUMISTA_TYPES_URL}/999/issues/iss-2016/prices")

    # -- Real production case: the UK 2012 20p price list. ----------------

    UK_20P_PRICES = [
        {"grade": "g", "price": 0.266846},
        {"grade": "vg", "price": 0.266846},
        {"grade": "f", "price": 0.280911},
        {"grade": "vf", "price": 0.280911},
        {"grade": "xf", "price": 0.359662},
        {"grade": "au", "price": 0.406070},
        {"grade": "unc", "price": 1.160200},
    ]

    def _price_response(self, prices):
        response = mock.Mock(status_code=200, text=json.dumps({"prices": prices}))
        response.json.return_value = {"prices": prices}
        return response

    def test_f12_grade_selects_the_f_entry_not_the_nearest_fallback(self):
        """The exact live regression: requesting "F-12 (visual estimate)"
        must select the "f" price (0.280911), not fall through to the
        nearest-available fallback, which happened to also land on "vf"
        (same price here) but is not guaranteed to for other coins."""
        coinlens_app.NUMISTA_API_KEY = "test-key"
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._price_response(self.UK_20P_PRICES)):
            result = coinlens_app.fetch_numista_price(5628, 144284, "F-12 (visual estimate)")

        self.assertIsNotNone(result)
        self.assertTrue(result["exact_grade_match"])
        self.assertEqual(result["grade"], "f")
        self.assertEqual(result["value"], 0.280911)

    def test_normalized_grade_present_in_response_is_selected_over_nearest_fallback(self):
        """General case (not just F-12): whenever the normalized requested
        grade exists among the returned prices, it must win - the
        nearest-available fallback is only for when it doesn't."""
        coinlens_app.NUMISTA_API_KEY = "test-key"
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._price_response(self.UK_20P_PRICES)):
            result = coinlens_app.fetch_numista_price(5628, 144284, "AU-55")

        self.assertTrue(result["exact_grade_match"])
        self.assertEqual(result["grade"], "au")
        self.assertEqual(result["value"], 0.406070)


class LookupNumistaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = coinlens_app.NUMISTA_API_KEY
        self._orig_openai_key = coinlens_app.OPENAI_API_KEY
        self._orig_mock_mode = coinlens_app.MOCK_MODE
        self._orig_use_mock = coinlens_app.USE_MOCK_COIN_RESPONSE
        coinlens_app.NUMISTA_API_KEY = "test-key"
        # should_use_mock_coin_response() also short-circuits on a missing
        # OpenAI key, independent of MOCK_MODE/USE_MOCK_COIN_RESPONSE.
        coinlens_app.OPENAI_API_KEY = "test-key"
        coinlens_app.MOCK_MODE = False
        coinlens_app.USE_MOCK_COIN_RESPONSE = False
        self.addCleanup(lambda: setattr(coinlens_app, "NUMISTA_API_KEY", self._orig_key))
        self.addCleanup(lambda: setattr(coinlens_app, "OPENAI_API_KEY", self._orig_openai_key))
        self.addCleanup(lambda: setattr(coinlens_app, "MOCK_MODE", self._orig_mock_mode))
        self.addCleanup(lambda: setattr(coinlens_app, "USE_MOCK_COIN_RESPONSE", self._orig_use_mock))

    def test_lookup_numista_sets_type_and_issue_ids_on_a_real_match(self):
        candidates = [{
            "id": 999, "title": "Dollar - Elizabeth II (Loon)",
            "issuer": {"name": "Canada"}, "min_year": 1987, "max_year": None,
        }]
        with mock.patch.object(coinlens_app, "search_numista_types", return_value=candidates), \
             mock.patch.object(coinlens_app, "fetch_numista_issues", return_value=[{"id": "iss-2016", "year": 2016}]), \
             mock.patch.object(coinlens_app, "fetch_numista_type_detail", return_value={"composition": {"text": "Nickel"}}):
            result = coinlens_app.lookup_numista(identification())

        self.assertEqual(result["numista_type_id"], 999)
        self.assertEqual(result["numista_issue_id"], "iss-2016")
        self.assertEqual(result["composition"]["text"], "Nickel")

    def test_lookup_numista_returns_none_when_no_issue_resolves(self):
        candidates = [{
            "id": 999, "title": "1 Dollar - Elizabeth II",
            "issuer": {"name": "Canada"}, "min_year": 1987, "max_year": 2020,
        }]
        with mock.patch.object(coinlens_app, "search_numista_types", return_value=candidates), \
             mock.patch.object(coinlens_app, "fetch_numista_issues", return_value=[{"id": "iss-1990", "year": 1990}]):
            result = coinlens_app.lookup_numista(identification())
        self.assertIsNone(result)


class IssuerResolutionTests(unittest.TestCase):
    """Numista's /types `issuer` param expects a real issuer code, not an
    arbitrary country string - these cover resolving one from Numista's own
    /issuers list (never a hardcoded guess), the small alias map for
    obvious AI phrasing, the in-process cache, and safe failure modes."""

    def setUp(self):
        self._orig_key = coinlens_app.NUMISTA_API_KEY
        self._orig_cache = dict(coinlens_app._numista_issuer_cache)
        coinlens_app.NUMISTA_API_KEY = "test-key"
        coinlens_app._numista_issuer_cache["by_name"] = None
        coinlens_app._numista_issuer_cache["fetched_at"] = 0.0
        self.addCleanup(lambda: setattr(coinlens_app, "NUMISTA_API_KEY", self._orig_key))
        self.addCleanup(lambda: coinlens_app._numista_issuer_cache.update(self._orig_cache))

    def _issuers_response(self, issuers):
        resp = mock.Mock(status_code=200)
        resp.text = json.dumps({"issuers": issuers})
        resp.json.return_value = {"issuers": issuers}
        return resp

    def test_resolves_a_real_issuer_name_to_its_code(self):
        issuers = [{"code": "royaume-uni", "name": "United Kingdom"}, {"code": "france", "name": "France"}]
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._issuers_response(issuers)):
            code = coinlens_app.resolve_numista_issuer_code("United Kingdom")
        self.assertEqual(code, "royaume-uni")

    def test_handles_uk_alias(self):
        issuers = [{"code": "royaume-uni", "name": "United Kingdom"}]
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._issuers_response(issuers)):
            code = coinlens_app.resolve_numista_issuer_code("UK")
        self.assertEqual(code, "royaume-uni")

    def test_handles_usa_and_us_aliases(self):
        issuers = [{"code": "etats-unis", "name": "United States"}]
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._issuers_response(issuers)):
            code_usa = coinlens_app.resolve_numista_issuer_code("USA")
            code_us = coinlens_app.resolve_numista_issuer_code("US")
        self.assertEqual(code_usa, "etats-unis")
        self.assertEqual(code_us, "etats-unis")

    def test_matches_case_insensitively(self):
        issuers = [{"code": "canada", "name": "Canada"}]
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._issuers_response(issuers)):
            code = coinlens_app.resolve_numista_issuer_code("cAnAdA")
        self.assertEqual(code, "canada")

    def test_caches_issuer_list_and_does_not_refetch_on_every_call(self):
        issuers = [{"code": "canada", "name": "Canada"}]
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._issuers_response(issuers)) as mock_get:
            coinlens_app.resolve_numista_issuer_code("Canada")
            coinlens_app.resolve_numista_issuer_code("Canada")
            coinlens_app.resolve_numista_issuer_code("Canada")
        self.assertEqual(mock_get.call_count, 1)

    def test_unresolvable_country_returns_none_without_raising(self):
        issuers = [{"code": "canada", "name": "Canada"}]
        with mock.patch.object(coinlens_app.requests, "get", return_value=self._issuers_response(issuers)):
            code = coinlens_app.resolve_numista_issuer_code("Atlantis")
        self.assertIsNone(code)

    def test_issuer_fetch_failure_returns_none_without_raising(self):
        with mock.patch.object(coinlens_app.requests, "get", side_effect=coinlens_app.requests.RequestException("boom")):
            code = coinlens_app.resolve_numista_issuer_code("Canada")
        self.assertIsNone(code)


class StructuredSearchTests(unittest.TestCase):
    """Reproduces the real 2012 UK 20 pence case: free-text search for
    "United Kingdom 20 pence" returned mostly Isle of Man candidates, and
    every one correctly failed issue validation (1982/1983 issues only) -
    the search step itself needs to give the pipeline a fair shot via a
    structured, issuer-scoped query instead of free text."""

    def setUp(self):
        self._orig_key = coinlens_app.NUMISTA_API_KEY
        coinlens_app.NUMISTA_API_KEY = "test-key"
        self.addCleanup(lambda: setattr(coinlens_app, "NUMISTA_API_KEY", self._orig_key))

    def _search_response(self, results):
        resp = mock.Mock(status_code=200)
        resp.text = json.dumps({"types": results})
        resp.json.return_value = {"types": results}
        return resp

    def test_uk_20_pence_2012_structured_search_includes_denomination_issuer_year_category(self):
        candidates = [{"id": 10799, "title": "20 Pence - Elizabeth II", "issuer": {"name": "United Kingdom"}}]
        with mock.patch.object(coinlens_app, "resolve_numista_issuer_code", return_value="royaume-uni"), \
             mock.patch.object(coinlens_app.requests, "get", return_value=self._search_response(candidates)) as mock_get:
            results = coinlens_app.search_numista_types(
                identification(country="United Kingdom", denomination="20 pence", year="2012")
            )

        self.assertEqual(results, candidates)
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["q"], "20 pence")
        self.assertEqual(params["issuer"], "royaume-uni")
        self.assertEqual(params["year"], 2012)
        self.assertEqual(params["category"], "coin")

    def test_country_is_not_stuffed_into_q_when_issuer_is_available(self):
        with mock.patch.object(coinlens_app, "resolve_numista_issuer_code", return_value="royaume-uni"), \
             mock.patch.object(coinlens_app.requests, "get", return_value=self._search_response([])) as mock_get:
            coinlens_app.search_numista_types(
                identification(country="United Kingdom", denomination="20 pence", year="2012")
            )
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("united kingdom", params["q"].lower())

    def test_issuer_resolution_failure_falls_back_to_denomination_and_year_search(self):
        fallback_candidates = [{"id": 1, "title": "20 Pence"}]
        with mock.patch.object(coinlens_app, "resolve_numista_issuer_code", return_value=None), \
             mock.patch.object(coinlens_app.requests, "get", return_value=self._search_response(fallback_candidates)) as mock_get:
            results = coinlens_app.search_numista_types(
                identification(country="United Kingdom", denomination="20 pence", year="2012")
            )

        self.assertEqual(results, fallback_candidates)
        self.assertEqual(mock_get.call_count, 1)  # no wasted structured attempt when issuer resolution already failed
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("issuer", params)
        self.assertEqual(params["q"], "20 pence")
        self.assertEqual(params["year"], 2012)
        self.assertEqual(params["category"], "coin")

    def test_structured_search_with_no_candidates_falls_back_to_denomination_only(self):
        empty = self._search_response([])
        fallback_candidates = [{"id": 2, "title": "20 Pence"}]
        filled = self._search_response(fallback_candidates)
        with mock.patch.object(coinlens_app, "resolve_numista_issuer_code", return_value="royaume-uni"), \
             mock.patch.object(coinlens_app.requests, "get", side_effect=[empty, filled]) as mock_get:
            results = coinlens_app.search_numista_types(
                identification(country="United Kingdom", denomination="20 pence", year="2012")
            )

        self.assertEqual(results, fallback_candidates)
        self.assertEqual(mock_get.call_count, 2)
        fallback_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertNotIn("issuer", fallback_params)


class MockModeUnaffectedTests(unittest.TestCase):
    def setUp(self):
        self._orig_mock_mode = coinlens_app.MOCK_MODE
        coinlens_app.MOCK_MODE = True
        self.addCleanup(lambda: setattr(coinlens_app, "MOCK_MODE", self._orig_mock_mode))

    def test_lookup_numista_mock_mode_is_unaffected_by_issuer_resolution(self):
        with mock.patch.object(coinlens_app, "search_numista_types") as mock_search, \
             mock.patch.object(coinlens_app, "resolve_numista_issuer_code") as mock_resolve:
            result = coinlens_app.lookup_numista(identification())
        mock_search.assert_not_called()
        mock_resolve.assert_not_called()
        self.assertEqual(result, dict(coinlens_app.MOCK_NUMISTA))


if __name__ == "__main__":
    unittest.main()
