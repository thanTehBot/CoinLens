import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, RefreshControl, SafeAreaView, ScrollView, Text, TextInput, TouchableOpacity, View } from "react-native";
import GoldCoin from "../../components/GoldCoin";
import Header from "../../components/Header";
import styles from "../../theme/styles";
import { fetchMyScans } from "../../api/scans";
import { groupScansByCoin, formatScanValue } from "../../api/scanHistoryLogic";

export default function StatsScreen({ navigate }) {
  const [scans, setScans] = useState([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const refreshScans = useCallback(async () => {
    const current = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const rows = await fetchMyScans();
      if (current === requestId.current) setScans(rows);
    } catch (e) {
      if (current === requestId.current) {
        setScans([]);
        setError(e.message || "Could not load your saved scans.");
      }
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshScans();
    return () => { requestId.current += 1; };
  }, [refreshScans]);

  const coinList = groupScansByCoin(scans);
  const filtered = query.trim()
    ? scans.filter(s => s.coin.toLowerCase().includes(query.trim().toLowerCase()))
    : scans;

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Detailed Stats" onBack={() => navigate("account")} />
      <ScrollView
        contentContainerStyle={styles.accountContainer}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refreshScans} tintColor="#FFD700" />}
      >
        <TouchableOpacity style={styles.detailedStatsBtn} onPress={refreshScans} disabled={loading} accessibilityRole="button">
          <Text style={styles.detailedStatsBtnText}>{loading ? "Loading scans..." : "Refresh scans"}</Text>
        </TouchableOpacity>
        {loading && scans.length === 0 ? (
          <ActivityIndicator color="#FFD700" accessibilityLabel="Loading saved scans" />
        ) : error ? (
          <Text style={styles.authError} accessibilityRole="alert">{error}</Text>
        ) : scans.length === 0 ? (
          <View style={styles.center}>
            <Text style={styles.pageSubtitle}>No saved scans yet. Start scanning coins!</Text>
          </View>
        ) : (
          <>
            <Text style={styles.sectionTitle}>By Coin Type</Text>
            {coinList.map(([coin, { count, totalValue, valuedCount }]) => (
              <View key={coin} style={styles.statCoinRow}>
                <GoldCoin size={36} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.statCoinName}>{coin}</Text>
                  <Text style={styles.statCoinSub}>
                    {count} scanned ? {valuedCount
                      ? formatScanValue(totalValue / valuedCount) + " avg (" + valuedCount + " valued)"
                      : "Value unavailable"}
                  </Text>
                </View>
                <View style={styles.statCoinBadge}>
                  <Text style={styles.statCoinBadgeText}>{count}</Text>
                </View>
              </View>
            ))}

            <Text style={styles.sectionTitle}>Saved Scans</Text>
            <View style={styles.searchBar}>
              <TextInput
                style={styles.searchInput}
                placeholder="Search your coins..."
                accessibilityLabel="Search your saved coins"
                placeholderTextColor="rgba(255,215,0,0.3)"
                value={query}
                onChangeText={setQuery}
                autoCapitalize="none"
                autoCorrect={false}
              />
              {query.length > 0 && (
                <TouchableOpacity onPress={() => setQuery("")} accessibilityRole="button" accessibilityLabel="Clear search">
                  <Text style={styles.searchClear}>?</Text>
                </TouchableOpacity>
              )}
            </View>

            {filtered.length === 0 ? (
              <Text style={styles.searchEmpty}>No coins match your search.</Text>
            ) : filtered.map(scan => (
              <View key={scan.id} style={styles.recentItem}>
                <GoldCoin size={38} />
                <View style={styles.recentText}>
                  <Text style={styles.recentName}>{scan.coin}</Text>
                  <Text style={styles.recentDetail}>
                    {scan.time && !Number.isNaN(Date.parse(scan.time))
                      ? new Date(scan.time).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
                      : "Date unavailable"}
                    {" ? " + formatScanValue(scan.value)}
                  </Text>
                </View>
              </View>
            ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
