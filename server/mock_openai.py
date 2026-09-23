MOCK_MARKER = "MOCK RESPONSE FROM RENDER FLASK SERVER"

MOCK_IDENTIFICATION = {
    "coin_name": "1946 United States Lincoln Wheat Cent",
    "country": "United States",
    "denomination": "One Cent",
    "year": "1946",
    "mint_mark": None,
    "estimated_grade": "VF-30",
    "description": f"{MOCK_MARKER}: deterministic mock identification for backend round-trip testing.",
    "mint_errors": [],
    "varieties": "Lincoln Wheat Cent",
    "error_premium": False,
    "special_notes": f"{MOCK_MARKER}: canned 1946 Lincoln Wheat Cent result.",
    "status": "identified",
    "identifiable": True,
    "confidence": 94,
    "alternatives": [
        {"coin": "1946-D Lincoln Wheat Cent", "confidence": 42},
        {"coin": "1946-S Lincoln Wheat Cent", "confidence": 31},
    ],
}

MOCK_NUMISTA = {
    "id": 784,
    "title": "Lincoln Cent - Wheat reverse",
    "url": "https://en.numista.com/catalogue/pieces908.html",
    "composition": {"text": "Bronze"},
    "weight": 3.11,
    "size": 19.0,
    "references": [{"type": "PCGS", "number": "2731"}],
    "note": MOCK_MARKER,
}

MOCK_PCGS = {
    "grade": "VF-30",
    "price": 12.34,
    "designation": "Brown",
    "source_note": f"{MOCK_MARKER}: canned PCGS priceguide-shaped response; this is not automated grading.",
}

MOCK_VALUATION = {
    "status": "available",
    "estimated_value": 12.34,
    "currency": "USD",
    "source": "CoinLens deterministic mock",
    "low": 10.0,
    "high": 15.0,
    "condition_assumed": "VF-30",
    "error_value_note": None,
    "reasoning": f"{MOCK_MARKER}: canned valuation for a 1946 Lincoln Wheat Cent in VF condition.",
}

MOCK_SUMMARY = (
    f"{MOCK_MARKER}: This is a 1946 Lincoln Wheat Cent in VF condition. "
    "Its wheat reverse makes it a classic beginner-friendly collectible. "
    "The mock valuation is $12.34 so the full capture-upload-result flow is easy to verify."
)

MOCK_EBAY_LISTING = {
    "title": "1946 Lincoln Wheat Cent VF Brown - CoinLens Mock",
    "subtitle": MOCK_MARKER,
    "description": f"{MOCK_MARKER}: Deterministic listing draft for a 1946 United States Lincoln Wheat Cent graded about VF-30.",
    "item_specifics": [
        {"label": "Year", "value": "1946"},
        {"label": "Denomination", "value": "Small Cent"},
        {"label": "Country/Region of Manufacture", "value": "United States"},
        {"label": "Grade", "value": "VF"},
        {"label": "Certification", "value": "Uncertified"},
    ],
    "shipping_notes": f"{MOCK_MARKER}: Ship protected in a 2x2 holder with tracking.",
}

MOCK_SCAN_ROW = {
    "Coin": "1946 United States Lincoln Wheat Cent",
    "Time": "2026-01-01T00:00:00.000Z",
    "User": "Mock User",
    "Value": 12.34,
    "Marker": MOCK_MARKER,
}


def build_mock_coin_result(front_image_present=True, back_image_present=False):
    return {
        "identification": dict(MOCK_IDENTIFICATION),
        "valuation": dict(MOCK_VALUATION),
        "numista": dict(MOCK_NUMISTA),
        "pcgs": dict(MOCK_PCGS),
        "summary": MOCK_SUMMARY,
        "marker": MOCK_MARKER,
        "meta": {
            "mock": True,
            "front_image_received": bool(front_image_present),
            "back_image_received": bool(back_image_present),
            "marker": MOCK_MARKER,
        },
    }
