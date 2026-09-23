import base64
import json
import os
import sys
import time
import unittest
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import app as coinlens_app
import auth as coinlens_auth


TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"
FRONT_BYTES = b"\xff\xd8\xff\xe0coinlens-front-image"
BACK_BYTES = b"\xff\xd8\xff\xe0coinlens-back-image"


def b64(data):
    return base64.b64encode(data).decode("ascii")


def evidence(basis, visible_text):
    return {"basis": basis, "visible_text": visible_text}


def observations(**overrides):
    """Grounded observations for a UK 2012 20 pence (the known-correct
    real-device coin); override individual fields to model a failure."""
    base = {
        "observed_text_front": "ELIZABETH II D G REG F D 2012",
        "observed_text_back": "TWENTY PENCE",
        "observed_numerals": ["2012"],
        "observed_shape": "polygonal",
        "observed_side_count": 7,
        "observed_color_or_material": "silver-colored",
        "observed_bimetallic": "no",
        "country_evidence": evidence("derived_from_visible_markings", "ELIZABETH II D G REG F D"),
        "denomination_evidence": evidence("read_on_coin", "TWENTY PENCE"),
        "year_evidence": evidence("read_on_coin", "2012"),
    }
    base.update(overrides)
    return base


def model_response(**overrides):
    base = {
        "observations": observations(),
        "status": "identified", "coin_name": "2012 United Kingdom 20 Pence",
        "country": "United Kingdom", "denomination": "20 pence", "year": "2012",
        "mint_mark": None, "variant": "ordinary", "estimated_grade": "VF-30", "confidence": 90,
        "description": "", "mint_errors": [], "varieties": None, "error_premium": False,
        "special_notes": "", "unidentifiable_reason": None, "alternatives": [],
    }
    base.update(overrides)
    return base


# The three real production false positives, shaped as the new schema would
# carry them when the model's own observations don't support its claim.
UK_50P_2011_FALSE_POSITIVE = model_response(
    confidence=91, denomination="50 pence", year="2011", coin_name="2011 United Kingdom 50 Pence",
    observations=observations(
        observed_text_front="ELIZABETH II unclear", observed_text_back="unclear", observed_numerals=[],
        denomination_evidence=evidence("design_recognition", "guess based on shape"),
        year_evidence=evidence("design_recognition", ""),
    ),
)
MEXICO_1_PESO_1910_FALSE_POSITIVE = model_response(
    confidence=82, country="Mexico", denomination="1 peso", year="1910", coin_name="1910 Mexico 1 Peso",
    observations=observations(
        observed_text_front="unclear", observed_text_back="unclear", observed_numerals=[],
        country_evidence=evidence("design_recognition", ""),
        denomination_evidence=evidence("design_recognition", ""),
        year_evidence=evidence("not_visible", ""),
    ),
)
UK_1_POUND_2017_FALSE_POSITIVE = model_response(
    confidence=93, denomination="£1 (one pound)", year="2017", coin_name="2017 United Kingdom £1",
    observations=observations(
        observed_text_back="unclear", observed_numerals=["20"],
        denomination_evidence=evidence("design_recognition", "unsupported"),
        year_evidence=evidence("design_recognition", ""),
    ),
)


class EvidenceGateTests(unittest.TestCase):
    def test_fully_grounded_country_denomination_year_is_identified(self):
        result = coinlens_app.normalize_identification(model_response())
        self.assertTrue(result["identifiable"])
        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["year"], "2012")

    def test_illegible_year_is_uncertain_even_when_model_says_identified(self):
        result = coinlens_app.normalize_identification(model_response(
            year="Illegible; possibly 2012",
            observations=observations(observed_numerals=[], year_evidence=evidence("not_visible", "")),
        ))
        self.assertFalse(result["identifiable"])
        self.assertEqual(result["status"], "uncertain")

    def test_non_exact_year_strings_never_qualify(self):
        for year in ["Unknown", "Possibly 2012", "Maybe 1910", "Illegible", "Circa 1900", "2012?", "1990s", "201", "3024"]:
            with self.subTest(year=year):
                self.assertFalse(coinlens_app._is_exact_year(year))
                result = coinlens_app.normalize_identification(model_response(year=year))
                self.assertFalse(result["identifiable"])
        self.assertTrue(coinlens_app._is_exact_year("2012"))

    def test_unclear_denomination_is_uncertain(self):
        for denomination in ["Unclear", "Possibly 50 pence", "20 or 50 pence", "unknown"]:
            with self.subTest(denomination=denomination):
                result = coinlens_app.normalize_identification(model_response(denomination=denomination))
                self.assertFalse(result["identifiable"])

    def test_confidence_91_with_inferred_year_evidence_is_uncertain(self):
        result = coinlens_app.normalize_identification(model_response(
            confidence=91,
            observations=observations(year_evidence=evidence("design_recognition", "")),
        ))
        self.assertFalse(result["identifiable"])
        self.assertEqual(result["confidence"], 91)  # reported as-is; it just can't override the gate

    def test_confidence_93_with_unsupported_denomination_evidence_is_uncertain(self):
        result = coinlens_app.normalize_identification(model_response(
            confidence=93,
            observations=observations(denomination_evidence=evidence("design_recognition", "")),
        ))
        self.assertFalse(result["identifiable"])

    def test_year_claimed_as_read_but_absent_from_transcription_is_uncertain(self):
        """The model says it read "2011" but transcribed no such digits
        anywhere - that "reading" was recalled, not seen."""
        result = coinlens_app.normalize_identification(model_response(
            year="2011",
            observations=observations(
                observed_text_front="ELIZABETH II D G REG F D", observed_numerals=[],
                year_evidence=evidence("read_on_coin", "20__"),
            ),
        ))
        self.assertFalse(result["identifiable"])

    def test_derived_year_from_visible_era_date_is_accepted(self):
        result = coinlens_app.normalize_identification(model_response(
            country="Japan", denomination="100 yen", year="1989",
            observations=observations(
                observed_text_front="日本国 百円", observed_text_back="100 平成元年", observed_numerals=["100"],
                country_evidence=evidence("read_on_coin", "日本国"),
                denomination_evidence=evidence("read_on_coin", "100 百円"),
                year_evidence=evidence("derived_from_visible_markings", "平成元年"),
            ),
        ))
        self.assertTrue(result["identifiable"])

    def test_missing_observations_block_is_uncertain(self):
        data = model_response()
        del data["observations"]
        self.assertFalse(coinlens_app.normalize_identification(data)["identifiable"])

    def test_uk_50p_2011_false_positive_is_rejected(self):
        self.assertFalse(coinlens_app.normalize_identification(UK_50P_2011_FALSE_POSITIVE)["identifiable"])

    def test_mexico_1_peso_1910_false_positive_is_rejected(self):
        self.assertFalse(coinlens_app.normalize_identification(MEXICO_1_PESO_1910_FALSE_POSITIVE)["identifiable"])

    def test_uk_1_pound_2017_false_positive_is_rejected(self):
        self.assertFalse(coinlens_app.normalize_identification(UK_1_POUND_2017_FALSE_POSITIVE)["identifiable"])

    def test_gate_rejection_is_logged_with_reasons(self):
        with self.assertLogs(coinlens_app.app.logger, level="INFO") as logs:
            coinlens_app.normalize_identification(MEXICO_1_PESO_1910_FALSE_POSITIVE)
        line = next(message for message in logs.output if "evidence gate rejected" in message)
        self.assertIn("year is not supported by legible evidence", line)
        self.assertIn("country is not supported by legible evidence", line)

    def test_schema_asks_for_observations_before_identification(self):
        schema = coinlens_app.IDENTIFICATION_JSON_SCHEMA
        self.assertEqual(next(iter(schema["properties"])), "observations")
        self.assertIn("observations", schema["required"])
        self.assertIn("variant", schema["required"])
        obs = schema["properties"]["observations"]
        self.assertEqual(set(obs["required"]), set(obs["properties"]))
        for field in ("observed_text_front", "observed_text_back", "observed_numerals", "observed_shape",
                      "observed_color_or_material", "observed_bimetallic", "country_evidence",
                      "denomination_evidence", "year_evidence"):
            self.assertIn(field, obs["properties"])

    def test_prompt_states_the_observation_first_rules(self):
        prompt = coinlens_app.IDENTIFICATION_PROMPT
        for phrase in ["STEP 1 - OBSERVE", "STEP 2 - IDENTIFY", "Never invent an inscription or a year",
                       "Never infer the year from the dates a coin series was issued",
                       "Do not infer the country solely from a familiar portrait",
                       "Resemblance to a coin you remember is NOT visible evidence"]:
            self.assertIn(phrase, prompt)


class PhysicalConsistencyTests(unittest.TestCase):
    UK_1_POUND_2017_CATALOG = {
        "numista_type_id": 100658, "numista_issue_id": 321440, "id": 100658,
        "title": "1 Pound - Elizabeth II (5th portrait)",
        "shape": "Dodecagonal (12-sided)",
        "composition": {"text": "Bimetallic: nickel-plated alloy centre in nickel-brass ring"},
    }

    def test_single_metal_seven_sided_photo_contradicts_bimetallic_twelve_sided_catalog(self):
        reasons = coinlens_app.physical_contradictions(observations(), self.UK_1_POUND_2017_CATALOG)
        self.assertEqual(len(reasons), 2)

    def test_uncertain_physical_observations_never_contradict(self):
        obs = observations(observed_shape="unclear", observed_side_count=None, observed_bimetallic="unclear")
        self.assertEqual(coinlens_app.physical_contradictions(obs, self.UK_1_POUND_2017_CATALOG), [])

    def test_catalog_without_shape_or_composition_never_contradicts(self):
        self.assertEqual(coinlens_app.physical_contradictions(observations(), {"numista_type_id": 1}), [])

    def test_matching_physical_traits_report_no_contradiction(self):
        catalog = {"shape": "Equilateral curve heptagon (7-sided)", "composition": {"text": "Copper-nickel"}}
        self.assertEqual(coinlens_app.physical_contradictions(observations(), catalog), [])

    def test_visible_bimetallic_photo_contradicts_single_metal_catalog(self):
        obs = observations(observed_bimetallic="yes", observed_shape="round", observed_side_count=None)
        reasons = coinlens_app.physical_contradictions(obs, {"shape": "Round", "composition": {"text": "Nickel-brass"}})
        self.assertEqual(len(reasons), 1)

    def test_shape_side_count_parsing(self):
        self.assertEqual(coinlens_app.numista_shape_side_count("Dodecagonal (12-sided)"), 12)
        self.assertEqual(coinlens_app.numista_shape_side_count("Heptagonal"), 7)
        self.assertEqual(coinlens_app.numista_shape_side_count("Round"), None)


def make_test_token(sub="user-123"):
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    claims = {"sub": sub, "aud": "authenticated", "iss": TEST_ISSUER, "iat": now, "exp": now + 3600}
    return jwt.encode(claims, private_key, algorithm="ES256"), private_key.public_key()


class IdentifyRouteGroundingTests(unittest.TestCase):
    def setUp(self):
        self.client = coinlens_app.app.test_client()
        coinlens_app.MOCK_MODE = False
        coinlens_app.USE_MOCK_COIN_RESPONSE = False
        coinlens_app.OPENAI_API_KEY = "test-key"
        coinlens_app.NUMISTA_API_KEY = ""
        coinlens_app.PCGS_BEARER_TOKEN = ""
        coinlens_app.DAILY_SCAN_LIMIT = 20
        original_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL
        self.addCleanup(lambda: setattr(coinlens_auth, "SUPABASE_URL", original_url))
        token, public_key = make_test_token()
        self.auth_headers = {"Authorization": f"Bearer {token}"}
        for name, value in (("_get_signing_key", public_key),):
            patcher = mock.patch.object(coinlens_auth, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (("count_api_usage_since", 0), ("insert_api_usage", {"id": "usage-1"})):
            patcher = mock.patch.object(coinlens_app, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.update_usage = mock.patch.object(coinlens_app, "update_api_usage").start()
        self.insert_scan = mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "scan-1"}).start()
        self.addCleanup(mock.patch.stopall)

    def post(self, model_data, front=FRONT_BYTES, back=BACK_BYTES):
        with mock.patch.object(coinlens_app.requests, "post") as mock_post:
            mock_post.return_value = mock.Mock(
                ok=True, status_code=200,
                json=lambda: {"status": "completed", "output_text": json.dumps(model_data)},
            )
            body = {"front_image": b64(front), "source": "camera"}
            if back is not None:
                body["back_image"] = b64(back)
            return self.client.post("/api/identify-coin", json=body, headers=self.auth_headers)

    # -- image fingerprints ---------------------------------------------

    def test_front_and_back_fingerprints_are_logged_without_image_data(self):
        with mock.patch.object(coinlens_app, "lookup_numista", return_value=None), \
             self.assertLogs(coinlens_app.app.logger, level="INFO") as logs:
            self.post(model_response())
        lines = [m for m in logs.output if "image input:" in m]
        self.assertEqual(len(lines), 2)
        front_sha = coinlens_app.hashlib.sha256(FRONT_BYTES).hexdigest()[:12]
        back_sha = coinlens_app.hashlib.sha256(BACK_BYTES).hexdigest()[:12]
        self.assertIn(f"front bytes={len(FRONT_BYTES)} mime=image/jpeg sha256={front_sha}", lines[0])
        self.assertIn(f"back bytes={len(BACK_BYTES)} mime=image/jpeg sha256={back_sha}", lines[1])
        self.assertNotEqual(front_sha, back_sha)
        self.assertFalse(any("byte-identical" in m for m in logs.output))
        everything = "\n".join(logs.output)
        self.assertNotIn(b64(FRONT_BYTES), everything)
        self.assertNotIn(b64(BACK_BYTES), everything)
        self.assertNotIn(coinlens_app.hashlib.sha256(FRONT_BYTES).hexdigest(), everything)

    def test_identical_front_and_back_bytes_log_a_warning(self):
        with mock.patch.object(coinlens_app, "lookup_numista", return_value=None), \
             self.assertLogs(coinlens_app.app.logger, level="INFO") as logs:
            self.post(model_response(), front=FRONT_BYTES, back=FRONT_BYTES)
        warnings = [m for m in logs.output if m.startswith("WARNING") and "byte-identical" in m]
        self.assertEqual(len(warnings), 1)

    def test_fingerprint_helper_is_stable_and_short(self):
        image = {"bytes": FRONT_BYTES, "mime": "image/jpeg"}
        self.assertEqual(coinlens_app.image_fingerprint(image), coinlens_app.image_fingerprint(dict(image)))
        self.assertEqual(len(coinlens_app.image_fingerprint(image)), 12)

    # -- persistence rule -----------------------------------------------

    def test_gate_failure_never_calls_numista_or_persists(self):
        for name, data in (("uk_50p_2011", UK_50P_2011_FALSE_POSITIVE),
                           ("mexico_1910", MEXICO_1_PESO_1910_FALSE_POSITIVE),
                           ("uk_1_pound_2017", UK_1_POUND_2017_FALSE_POSITIVE)):
            with self.subTest(case=name), \
                 mock.patch.object(coinlens_app, "lookup_numista") as lookup, \
                 mock.patch.object(coinlens_app, "search_numista_types") as search:
                self.insert_scan.reset_mock()
                response = self.post(data)
                self.assertEqual(response.status_code, 422)
                self.assertFalse(response.get_json()["identification"]["identifiable"])
                lookup.assert_not_called()
                search.assert_not_called()
                self.insert_scan.assert_not_called()

    def test_grounded_identification_without_numista_price_persists_with_null_value(self):
        with mock.patch.object(coinlens_app, "lookup_numista", return_value=None):
            response = self.post(model_response())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["valuation"]["status"], "unavailable")
        self.insert_scan.assert_called_once()
        self.assertIsNone(self.insert_scan.call_args[0][0]["estimated_value"])
        self.assertEqual(self.insert_scan.call_args[0][0]["year"], 2012)

    def assert_persisted_grounded_with_null_value(self, response):
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["identification"]["identifiable"])
        self.assertEqual(body["identification"]["status"], "identified")
        self.assertEqual(body["valuation"]["status"], "unavailable")
        self.insert_scan.assert_called_once()
        self.assertIsNone(self.insert_scan.call_args[0][0]["estimated_value"])
        self.update_usage.assert_called_with("usage-1", {"status": "identified", "scan_id": "scan-1"})

    def test_physical_contradiction_discards_catalog_match_but_keeps_grounded_identification(self):
        """Case A: the identification passed the visual evidence gate;
        Numista's matched record contradicts the observed shape/metal. The
        catalog match and its price are discarded - the grounded
        identification is still accepted and persisted with no value."""
        claimed = model_response(
            denomination="£1 (one pound)", year="2017", confidence=93,
            observations=observations(
                observed_text_front="ELIZABETH II D G REG F D 2017", observed_text_back="ONE POUND",
                observed_numerals=["2017"],
                denomination_evidence=evidence("read_on_coin", "ONE POUND"),
                year_evidence=evidence("read_on_coin", "2017"),
            ),
        )
        with mock.patch.object(coinlens_app, "lookup_numista",
                               return_value=dict(PhysicalConsistencyTests.UK_1_POUND_2017_CATALOG)), \
             mock.patch.object(coinlens_app, "fetch_numista_price", return_value={"value": 2.5, "grade": "vf"}) as price:
            response = self.post(claimed)
        self.assert_persisted_grounded_with_null_value(response)
        self.assertIsNone(response.get_json()["numista"])
        price.assert_not_called()
        self.assertEqual(self.insert_scan.call_args[0][0]["year"], 2017)

    def test_no_numista_candidate_persists_grounded_scan_with_null_value(self):
        """Case B."""
        coinlens_app.NUMISTA_API_KEY = "test-numista-key"
        self.addCleanup(setattr, coinlens_app, "NUMISTA_API_KEY", "")
        with mock.patch.object(coinlens_app, "search_numista_types", return_value=[]) as search:
            response = self.post(model_response())
        search.assert_called_once()
        self.assert_persisted_grounded_with_null_value(response)

    def test_ambiguous_numista_candidates_persist_grounded_scan_with_null_value(self):
        """Case C: two indistinguishable ordinary 20 pence types both have a
        2012 issue - Numista can't choose, so no value, but the grounded
        identification is still saved."""
        coinlens_app.NUMISTA_API_KEY = "test-numista-key"
        self.addCleanup(setattr, coinlens_app, "NUMISTA_API_KEY", "")
        candidates = [
            {"id": 1, "title": "20 Pence - Elizabeth II (Type A)", "issuer": {"name": "United Kingdom"},
             "object_type": {"name": "Standard circulation coins"}},
            {"id": 2, "title": "20 Pence - Elizabeth II (Type B)", "issuer": {"name": "United Kingdom"},
             "object_type": {"name": "Standard circulation coins"}},
        ]
        with mock.patch.object(coinlens_app, "search_numista_types", return_value=candidates), \
             mock.patch.object(coinlens_app, "fetch_numista_issues",
                               side_effect=lambda type_id: [{"id": type_id * 10, "year": 2012}]) as issues, \
             mock.patch.object(coinlens_app, "fetch_numista_price") as price:
            response = self.post(model_response())
        self.assertEqual(issues.call_count, 2)
        price.assert_not_called()
        self.assert_persisted_grounded_with_null_value(response)

if __name__ == "__main__":
    unittest.main()
