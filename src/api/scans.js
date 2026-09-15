import { supabase, getAccessToken } from "./supabase";
import { normalizeScan } from "./scanHistoryLogic";

// Ownership is enforced by public.scans SELECT RLS, not a client user_id filter.
export async function fetchMyScans() {
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
