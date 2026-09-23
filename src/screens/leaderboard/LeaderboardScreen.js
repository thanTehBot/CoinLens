import { useEffect, useRef, useState } from "react";
import { SafeAreaView, ScrollView, Text, TouchableOpacity, View } from "react-native";
import Header from "../../components/Header";
import styles from "../../theme/styles";
import { fetchLeaderboard } from "../../api/scans";

const REFRESH_INTERVAL_MS = 15000;

const LB_CATEGORIES = [
  { key: "scanned",  label: "Most Scanned", field: "scanned",  format: v => `${v} coins`   },
  { key: "netWorth", label: "Net Worth",    field: "netWorth", format: v => `$${v.toLocaleString()}` },
  { key: "avgValue", label: "Avg Coin Value",field: "avgValue", format: v => `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}/coin` },
  { key: "badges",   label: "Most Badges",  field: "badges",   format: v => `${v} badges`  },
];

function withAvgValue(u) {
  return { ...u, avgValue: u.scanned > 0 ? u.netWorth / u.scanned : 0 };
}

function memberDaysFrom(memberSince) {
  if (!memberSince) return 0;
  return Math.max(1, Math.floor((Date.now() - new Date(memberSince).getTime()) / 86400000));
}

// Safe aggregate rows from GET /api/leaderboard - scan_count/total_value/
// member_since/badge_count only, never another user's raw scan history.
// badge_count is computed authoritatively server-side (server/badges.py),
// identically regardless of which signed-in user is viewing. Matches "is
// this me" on user_id when the endpoint returns it; falls back to
// display_name so the screen still degrades gracefully against an older
// response shape.
function mapRpcRow(row, myUserId, myName) {
  const memberDays = memberDaysFrom(row.member_since);
  const isMe = row.user_id ? row.user_id === myUserId : row.display_name === myName;
  return {
    key: row.user_id || row.display_name,
    name: row.display_name || "Member",
    scanned: row.scan_count ?? 0,
    netWorth: Number(row.total_value ?? 0),
    memberDays,
    badges: row.badge_count ?? 0,
    isMe,
  };
}

export default function LeaderboardScreen({ navigate, user }) {
  const [cat, setCat] = useState("scanned");
  const [rows, setRows] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [flashedName, setFlashedName] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const previousCountsRef = useRef({});
  const category = LB_CATEGORIES.find(c => c.key === cat);

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const data = await fetchLeaderboard();
        if (!mounted) return;

        const previous = previousCountsRef.current;
        const next = {};
        let changedName = null;
        data.forEach(row => {
          const key = row.user_id || row.display_name;
          next[key] = row.scan_count;
          if (previous[key] != null && row.scan_count > previous[key]) {
            changedName = row.display_name;
          }
        });
        previousCountsRef.current = next;

        setRows(data.map(row => mapRpcRow(row, user.id, user.name)));
        setLastUpdated(new Date());
        setLoadError("");
        if (changedName) {
          setFlashedName(changedName);
          setTimeout(() => setFlashedName(null), 800);
        }
      } catch {
        if (mounted) setLoadError("Couldn't load the leaderboard. Pull to refresh.");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load();
    const id = setInterval(load, REFRESH_INTERVAL_MS);
    return () => { mounted = false; clearInterval(id); };
  }, [user.id]);

  const all = rows
    .map(withAvgValue)
    .sort((a, b) => b[category.field] - a[category.field])
    .map((u, i) => ({ ...u, rank: i + 1 }));

  const medals = ["🥇", "🥈", "🥉"];
  const updatedStr = lastUpdated
    ? lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "--";

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Leaderboard" onBack={() => navigate("home")} />
      <ScrollView contentContainerStyle={styles.accountContainer}>
        <View style={styles.lbLiveRow}>
          <View style={styles.lbLiveDot} />
          <Text style={styles.lbLiveText}>LIVE</Text>
          <Text style={styles.lbUpdatedText}>  Updated {updatedStr}</Text>
        </View>

        <View style={styles.lbCatRow}>
          {LB_CATEGORIES.map(c => (
            <TouchableOpacity key={c.key} style={[styles.lbCatBtn, cat === c.key && styles.lbCatBtnActive]} onPress={() => setCat(c.key)}>
              <Text style={[styles.lbCatText, cat === c.key && styles.lbCatTextActive]}>{c.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {loading ? (
          <Text style={styles.searchEmpty}>Loading leaderboard…</Text>
        ) : loadError ? (
          <Text style={styles.searchEmpty}>{loadError}</Text>
        ) : all.length === 0 ? (
          <Text style={styles.searchEmpty}>No collectors yet.</Text>
        ) : all.map((entry) => (
          <View key={entry.key} style={[styles.lbRow, entry.isMe && styles.lbRowMe, flashedName === entry.name && styles.lbRowFlash]}>
            <Text style={styles.lbRank}>
              {entry.rank <= 3 ? medals[entry.rank - 1] : `#${entry.rank}`}
            </Text>
            <View style={styles.lbInfo}>
              <Text style={[styles.lbName, entry.isMe && styles.lbNameMe]}>
                {entry.name}{entry.isMe ? "  (you)" : ""}
              </Text>
              <Text style={styles.lbSub}>{category.format(entry[category.field])}</Text>
            </View>
            <View style={[styles.lbBadge, entry.rank === 1 && styles.lbBadgeGold]}>
              <Text style={[styles.lbBadgeText, entry.rank === 1 && styles.lbBadgeTextGold]}>
                {category.format(entry[category.field])}
              </Text>
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
