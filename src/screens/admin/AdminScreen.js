import { useEffect, useState } from "react";
import { ActivityIndicator, SafeAreaView, ScrollView, Text, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import Header from "../../components/Header";
import { GOLD } from "../../theme/colors";
import styles from "../../theme/styles";
import { apiFetch } from "../../api/client";

export default function AdminScreen({ navigate }) {
  const [scans, setScans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadData() {
      try {
        let rows = [];
        try {
          const response = await apiFetch(`/api/scans`);
          const data = await response.json();
          rows = Array.isArray(data) ? data.filter(r => r.Coin) : [];
        } catch {
          rows = [];
        }

        const stored = await AsyncStorage.getItem("@coinlens_scans");
        const localScans = stored ? JSON.parse(stored) : [];
        const normalizedLocal = localScans.map((scan, index) => ({
          Coin: scan.coin || `Scan ${index + 1}`,
          Time: scan.time,
          User: scan.user || "Local User",
          Value: scan.value,
        }));

        const mergedRows = [...rows, ...normalizedLocal];
        setScans(mergedRows);
      } catch {
        setError("Failed to load data.");
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, []);

  const byUser = scans.reduce((acc, scan) => {
    const u = scan.User?.trim() || scan.user?.trim() || "Anonymous";
    if (!acc[u]) acc[u] = [];
    acc[u].push(scan);
    return acc;
  }, {});

  const userList = Object.entries(byUser).sort((a, b) => b[1].length - a[1].length);

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Admin Panel" onBack={() => navigate("account")} />
      <ScrollView contentContainerStyle={styles.accountContainer}>
        <View style={styles.adminBadge}>
          <Text style={styles.adminBadgeText}>🛡 Administrator</Text>
        </View>

        <View style={styles.statsRow}>
          <View style={styles.statBox}>
            <Text style={styles.statNumber}>{scans.length}</Text>
            <Text style={styles.statLabel}>Total{"\n"}Scans</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={styles.statNumber}>{userList.length}</Text>
            <Text style={styles.statLabel}>Unique{"\n"}Users</Text>
          </View>
        </View>

        {loading && <ActivityIndicator color={GOLD} style={{ marginTop: 20 }} />}
        {error ? <Text style={styles.authError}>{error}</Text> : null}

        {userList.length > 0 && (
          <>
            <Text style={styles.sectionTitle}>Users</Text>
            {userList.map(([userName, userScans]) => (
              <View key={userName} style={styles.adminUserCard}>
                <View style={styles.adminUserHeader}>
                  <View style={styles.adminUserAvatar}>
                    <Text style={styles.adminUserAvatarText}>{userName[0]?.toUpperCase() ?? "?"}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.adminUserName}>{userName}</Text>
                    <Text style={styles.adminUserCount}>{userScans.length} coin{userScans.length !== 1 ? "s" : ""} scanned</Text>
                  </View>
                </View>
                {userScans.slice(0, 3).map((s, i) => (
                  <View key={i} style={styles.adminScanRow}>
                    <Text style={styles.adminScanCoin}>{s.Coin}</Text>
                    <Text style={styles.adminScanTime}>{s.Time ? new Date(s.Time).toLocaleDateString() : ""}</Text>
                  </View>
                ))}
                {userScans.length > 3 && (
                  <Text style={styles.adminMore}>+{userScans.length - 3} more</Text>
                )}
              </View>
            ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
