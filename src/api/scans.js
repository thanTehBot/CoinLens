import { normalizeScan } from "./scanHistoryLogic";
import { supabase, getAccessToken } from "./supabase";
import { apiFetch } from "./client";

// Direct-to-Supabase reads for the signed-in user, under RLS. These never go
// through Flask: the architecture only routes trusted writes (the scan
// pipeline) through the server, while reads of a user's own data go straight
// to Supabase with the user's own session.
//
// The leaderboard is the one exception: each row now needs an authoritative
// badge_count computed from OTHER users' scans, which the client must never
// read directly (even under RLS) - so it goes through Flask's
// GET /api/leaderboard, which fetches those scans server-side with the
// service-role client and returns only aggregates + badge_count.

const SCAN_COLUMNS =
  "id, coin_name, country, denomination, year, mint_mark, estimated_grade, estimated_value, source, image_path, created_at, denom_canonical, is_foreign, local_date, local_hour, scanned_at";

export async function fetchMyScans() {
  const { data, error } = await supabase
    .from("scans")
    .select(SCAN_COLUMNS)
    .order("scanned_at", { ascending: true });

  if (error) throw error;
  return data || [];
}

export async function fetchLeaderboard() {
  const res = await apiFetch("/api/leaderboard");
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.error?.message || `Could not load the leaderboard (HTTP ${res.status}).`);
  }
  return data || [];
}

export async function fetchMyScanHistory() {
  let token;
  try {
    token = await getAccessToken();
  } catch {
    throw new Error("Unable to read your session. Please sign in again.");
  }
  if (!token) throw new Error("Sign in to view your saved scans.");

  const { data, error } = await supabase
    .schema("public")
    .from("scans")
    .select("id,coin_name,country,denomination,year,estimated_value,scanned_at,created_at")
    .order("scanned_at", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false });

  if (error) throw new Error("Could not load your saved scans. Please try again.");
  return (data || []).map(normalizeScan);
}
