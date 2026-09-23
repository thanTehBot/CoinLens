"""Authoritative badge-eligibility evaluator - the single source of truth
for badge rules going forward.

Ported 1:1 from src/badges/badges.js (same badge IDs, thresholds,
categories, and predicate logic - nothing redesigned). The JS file keeps
only display metadata (icon/name/desc/category) for the client to render;
eligibility itself is decided here, once, so a rule never needs to be
kept in sync in two places. If a badge rule ever needs to change, change
it here - and update src/badges/badges.js's *display* copy to match if
the description text says something different.

Badges are treated as derived current state, not permanent achievements
(see the badge-system audit): every check() call re-evaluates fresh
against whatever scans/profile data is passed in. Nothing here persists
anything.
"""

from datetime import date, datetime, timezone


def _net_worth(scans):
    return sum((s.get("estimated_value") or 0) for s in scans)


def _parse_timestamp(value):
    """Parses a Postgres/PostgREST timestamptz string into an aware
    datetime. Returns None for anything unparseable - never raises."""
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _member_days(member_created_at):
    parsed = _parse_timestamp(member_created_at)
    if parsed is None:
        return 0
    delta = datetime.now(timezone.utc) - parsed
    return max(0, delta.days)


def _local_date_parts(scan):
    raw = scan.get("local_date") or ((scan.get("scanned_at") or "")[:10] or None)
    if not raw:
        return None
    try:
        year_text, month_text, day_text = raw.split("-")
        year, month, day = int(year_text), int(month_text), int(day_text)
        return {"year": year, "month": month, "day": day, "date": date(year, month, day)}
    except (ValueError, TypeError):
        return None


def _on_month_day(scans, month, day):
    count = 0
    for scan in scans:
        parts = _local_date_parts(scan)
        if parts and parts["month"] == month and parts["day"] == day:
            count += 1
    return count


def _on_friday_the_13th(scans):
    # Python's date.weekday(): Monday=0 ... Friday=4 ... Sunday=6
    # (JS's Date.getDay() Friday=5 - different numbering, same day).
    count = 0
    for scan in scans:
        parts = _local_date_parts(scan)
        if parts and parts["day"] == 13 and parts["date"].weekday() == 4:
            count += 1
    return count


def _on_thanksgiving(scans):
    # US Thanksgiving: 4th Thursday of November. Python Thursday = weekday() 3.
    count = 0
    for scan in scans:
        parts = _local_date_parts(scan)
        if parts and parts["month"] == 11 and parts["date"].weekday() == 3 and 22 <= parts["day"] <= 28:
            count += 1
    return count


def _max_streak(scans, match_fn):
    max_run, current = 0, 0
    for scan in scans:
        if match_fn(scan):
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def _max_denom_streak(scans, denom):
    return _max_streak(scans, lambda s: s.get("denom_canonical") == denom)


def _max_any_denom_streak(scans):
    max_run, current, last = 0, 0, None
    for scan in scans:
        denom = scan.get("denom_canonical")
        current = current + 1 if (denom and denom == last) else (1 if denom else 0)
        last = denom
        max_run = max(max_run, current)
    return max_run


def _has_all_denoms(scans, denoms):
    owned = {s.get("denom_canonical") for s in scans}
    return all(d in owned for d in denoms)


def _has_scan_in_hour_range(scans, start_hour, end_hour):
    return any(
        isinstance(s.get("local_hour"), (int, float)) and start_hour <= s["local_hour"] < end_hour
        for s in scans
    )


def _has_rapid_pair(scans, within_ms):
    times = sorted(
        t.timestamp() * 1000
        for t in (_parse_timestamp(s.get("scanned_at")) for s in scans)
        if t is not None
    )
    return any(times[i] - times[i - 1] <= within_ms for i in range(1, len(times)))


def _has_old_coin(scans, before_year):
    return any(isinstance(s.get("year"), int) and s["year"] < before_year for s in scans)


def _year_span(scans):
    years = [s.get("year") for s in scans if isinstance(s.get("year"), int)]
    if len(years) < 2:
        return 0
    return max(years) - min(years)


def _has_denom(scans, denom):
    return any(s.get("denom_canonical") == denom for s in scans)


def _has_foreign(scans):
    return any(s.get("is_foreign") for s in scans)


# Each entry mirrors one BADGES[] entry in src/badges/badges.js exactly
# (same id, same category, same rule) - display metadata (icon/name/desc)
# intentionally lives only in the JS file now. check(scans, member_created_at)
# takes the user's own scans (any order in - streak-based checks rely on
# ascending scanned_at order, which callers must provide) and their real
# profile creation date (a timestamptz string, or None).
BADGES = [
    # Scanning
    {"id": "scan_1", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 1},
    {"id": "scan_10", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 10},
    {"id": "scan_25", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 25},
    {"id": "scan_50", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 50},
    {"id": "scan_100", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 100},
    {"id": "scan_250", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 250},
    {"id": "scan_500", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 500},
    {"id": "scan_1000", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 1000},
    {"id": "scan_2500", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 2500},
    {"id": "scan_5000", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 5000},
    {"id": "scan_10000", "category": "Scanning", "check": lambda scans, member_created_at: len(scans) >= 10000},
    # Net Worth
    {"id": "worth_1", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 1},
    {"id": "worth_10", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 10},
    {"id": "worth_50", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 50},
    {"id": "worth_100", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 100},
    {"id": "worth_500", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 500},
    {"id": "worth_1000", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 1000},
    {"id": "worth_10000", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 10000},
    {"id": "worth_25000", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 25000},
    {"id": "worth_100000", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 100000},
    {"id": "worth_500000", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 500000},
    {"id": "worth_1m", "category": "Net Worth", "check": lambda scans, member_created_at: _net_worth(scans) >= 1000000},
    # Membership
    {"id": "mem_join", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at)},
    {"id": "mem_7", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at) and _member_days(member_created_at) >= 7},
    {"id": "mem_30", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at) and _member_days(member_created_at) >= 30},
    {"id": "mem_180", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at) and _member_days(member_created_at) >= 180},
    {"id": "mem_365", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at) and _member_days(member_created_at) >= 365},
    {"id": "mem_730", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at) and _member_days(member_created_at) >= 730},
    {"id": "mem_1825", "category": "Member", "check": lambda scans, member_created_at: bool(member_created_at) and _member_days(member_created_at) >= 1825},
    # Seasonal
    {"id": "season_halloween", "category": "Seasonal", "check": lambda scans, member_created_at: _on_month_day(scans, 10, 31) >= 5},
    {"id": "season_friday13", "category": "Seasonal", "check": lambda scans, member_created_at: _on_friday_the_13th(scans) >= 1},
    {"id": "season_christmas", "category": "Seasonal", "check": lambda scans, member_created_at: _on_month_day(scans, 12, 25) >= 1},
    {"id": "season_newyear", "category": "Seasonal", "check": lambda scans, member_created_at: _on_month_day(scans, 1, 1) >= 3},
    {"id": "season_valentine", "category": "Seasonal", "check": lambda scans, member_created_at: _on_month_day(scans, 2, 14) >= 1},
    {"id": "season_stpatrick", "category": "Seasonal", "check": lambda scans, member_created_at: _on_month_day(scans, 3, 17) >= 1},
    {"id": "season_july4", "category": "Seasonal", "check": lambda scans, member_created_at: _on_month_day(scans, 7, 4) >= 4},
    {"id": "season_thanksgiving", "category": "Seasonal", "check": lambda scans, member_created_at: _on_thanksgiving(scans) >= 1},
    # Variety & streaks
    {"id": "var_nickel_streak", "category": "Variety", "check": lambda scans, member_created_at: _max_denom_streak(scans, "nickel") >= 5},
    {"id": "var_penny_streak", "category": "Variety", "check": lambda scans, member_created_at: _max_denom_streak(scans, "penny") >= 5},
    {"id": "var_dime_streak", "category": "Variety", "check": lambda scans, member_created_at: _max_denom_streak(scans, "dime") >= 5},
    {"id": "var_quarter_streak", "category": "Variety", "check": lambda scans, member_created_at: _max_denom_streak(scans, "quarter") >= 4},
    {"id": "var_wheat_streak", "category": "Variety", "check": lambda scans, member_created_at: _max_denom_streak(scans, "wheat-penny") >= 3},
    {"id": "var_on_a_roll", "category": "Variety", "check": lambda scans, member_created_at: _max_any_denom_streak(scans) >= 5},
    {"id": "var_full_set", "category": "Variety", "check": lambda scans, member_created_at: _has_all_denoms(scans, ["penny", "nickel", "dime", "quarter"])},
    {"id": "var_night_owl", "category": "Variety", "check": lambda scans, member_created_at: _has_scan_in_hour_range(scans, 0, 3)},
    {"id": "var_early_bird", "category": "Variety", "check": lambda scans, member_created_at: _has_scan_in_hour_range(scans, 4, 6)},
    {"id": "var_quickfire", "category": "Variety", "check": lambda scans, member_created_at: _has_rapid_pair(scans, 60000)},
    {"id": "var_old_soul", "category": "Variety", "check": lambda scans, member_created_at: _has_old_coin(scans, 1950)},
    {"id": "var_time_machine", "category": "Variety", "check": lambda scans, member_created_at: _year_span(scans) >= 100},
    # Coin Types
    {"id": "type_penny", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "penny")},
    {"id": "type_nickel", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "nickel")},
    {"id": "type_dime", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "dime")},
    {"id": "type_quarter", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "quarter")},
    {"id": "type_half", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "half-dollar")},
    {"id": "type_dollar", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "dollar")},
    {"id": "type_wheat", "category": "Coin Types", "check": lambda scans, member_created_at: _has_denom(scans, "wheat-penny")},
    {"id": "type_foreign", "category": "Coin Types", "check": lambda scans, member_created_at: _has_foreign(scans)},
]


def evaluate_badges(scans, member_created_at):
    """Runs every badge's check() against one user's real scans (expected
    in ascending scanned_at order - callers are responsible for that,
    since streak checks depend on it) and their real profile creation
    date. Returns (badge_count, earned_badge_ids) - never partial/cached,
    always the authoritative current result."""
    scans = scans or []
    earned = [badge["id"] for badge in BADGES if badge["check"](scans, member_created_at)]
    return len(earned), earned
