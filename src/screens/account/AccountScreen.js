import { SafeAreaView, ScrollView, Text, TouchableOpacity, View } from "react-native";
import GoldCoin from "../../components/GoldCoin";
import Header from "../../components/Header";
import styles from "../../theme/styles";
import { isAdminUser } from "../../../authLogic";

const RECENT_SCANS_LIMIT = 5;

export default function AccountScreen({ navigate, user, userScans, onSignOut }) {
  const scans = userScans || [];
  const initials = user.name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2);
  // userScans is oldest-first (for badge streak logic); show newest-first here.
  const recentScans = [...scans].reverse().slice(0, RECENT_SCANS_LIMIT);

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Account" onBack={() => navigate("home")} />
      <ScrollView contentContainerStyle={styles.accountContainer}>
        <View style={styles.profileSection}>
          <View style={[styles.avatarCircle, styles.avatarCircleLarge]}>
            <Text style={styles.avatarInitials}>{initials}</Text>
          </View>
          <Text style={styles.profileName}>{user.name}</Text>
          <Text style={styles.profileEmail}>{user.email}</Text>
          <View style={isAdminUser(user) ? styles.roleBadgeAdmin : styles.roleBadgeMember}>
            <Text style={styles.roleBadgeText}>{isAdminUser(user) ? "🛡 Admin" : "Member"}</Text>
          </View>
        </View>

        {(() => {
          const netWorth = scans.reduce((sum, s) => sum + (s.estimated_value ?? 0), 0);
          const timeLabel = (() => {
            if (!user.createdAt) return "New";
            const days = Math.floor((Date.now() - user.createdAt) / 86400000);
            if (days < 1) return "Today";
            if (days < 30) return `${days}d`;
            if (days < 365) return `${Math.floor(days / 30)}mo`;
            return `${Math.floor(days / 365)}yr`;
          })();
          return (
            <View style={styles.statsGrid}>
              <View style={styles.statBox}>
                <Text style={styles.statNumber}>{scans.length}</Text>
                <Text style={styles.statLabel}>Coins Scanned</Text>
              </View>
              <View style={styles.statBox}>
                <Text style={styles.statNumber}>{timeLabel}</Text>
                <Text style={styles.statLabel}>Time as Member</Text>
              </View>
              <View style={[styles.statBox, styles.statBoxWide]}>
                <Text style={styles.statNumber}>${netWorth.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}</Text>
                <Text style={styles.statLabel}>Est. Net Worth</Text>
              </View>
            </View>
          );
        })()}

        <TouchableOpacity style={styles.detailedStatsBtn} onPress={() => navigate("stats")}>
          <Text style={styles.detailedStatsBtnText}>Detailed Stats →</Text>
        </TouchableOpacity>

        <Text style={styles.sectionTitle}>Recent Scans</Text>

        {recentScans.length === 0 ? (
          <Text style={styles.searchEmpty}>No coins scanned yet.</Text>
        ) : recentScans.map((scan) => (
          <View key={scan.id} style={styles.recentItem}>
            <GoldCoin size={38} />
            <View style={styles.recentText}>
              <Text style={styles.recentName}>{scan.coin_name}</Text>
              <Text style={styles.recentDetail}>
                {new Date(scan.scanned_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
                {scan.estimated_value != null ? `  ·  ~$${scan.estimated_value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : ""}
              </Text>
            </View>
          </View>
        ))}

        {isAdminUser(user) && (
          <View style={styles.adminPanelGlow}>
            <TouchableOpacity style={styles.adminPanelBtn} onPress={() => navigate("admin")}>
              <Text style={styles.adminPanelBtnText}>🛡 Admin Panel</Text>
            </TouchableOpacity>
          </View>
        )}

        <TouchableOpacity style={styles.signOutBtn} onPress={onSignOut}>
          <Text style={styles.signOutText}>Sign Out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}
