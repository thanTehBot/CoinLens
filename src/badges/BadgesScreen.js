import { useEffect, useState } from "react";
import { SafeAreaView, ScrollView, Text, View } from "react-native";
import Header from "../components/Header";
import styles from "../theme/styles";
import { BADGES, BADGE_CATEGORIES } from "./badges";
import { fetchMyBadges } from "../api/client";

export default function BadgesScreen({ navigate }) {
  const [earned, setEarned] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const { earned_badge_ids } = await fetchMyBadges();
        if (mounted) {
          setEarned(new Set(earned_badge_ids || []));
          setLoadError("");
        }
      } catch {
        if (mounted) setLoadError("Couldn't load your badges. Pull to refresh.");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load();
    return () => { mounted = false; };
  }, []);

  const earnedCount = earned.size;

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Badges" onBack={() => navigate("home")} />
      <ScrollView contentContainerStyle={styles.badgesScroll}>
        {loading ? (
          <Text style={styles.searchEmpty}>Loading badges…</Text>
        ) : loadError ? (
          <Text style={styles.searchEmpty}>{loadError}</Text>
        ) : (
          <>
            <View style={styles.badgesProgressRow}>
              <Text style={styles.badgesProgressText}>{earnedCount} / {BADGES.length} earned</Text>
              <View style={styles.badgesProgressTrack}>
                <View style={[styles.badgesProgressFill, { width: `${(earnedCount / BADGES.length) * 100}%` }]} />
              </View>
            </View>

            {BADGE_CATEGORIES.map(cat => {
              const group = BADGES.filter(b => b.category === cat);
              return (
                <View key={cat} style={styles.badgesCatSection}>
                  <Text style={styles.badgesCatTitle}>{cat}</Text>
                  <View style={styles.badgesGrid}>
                    {group.map(badge => {
                      const isEarned = earned.has(badge.id);
                      return (
                        <View key={badge.id} style={[styles.badgeCard, isEarned && styles.badgeCardEarned]}>
                          <Text style={[styles.badgeCardIcon, !isEarned && styles.badgeCardIconLocked]}>
                            {isEarned ? badge.icon : "🔒"}
                          </Text>
                          <Text style={[styles.badgeCardName, !isEarned && styles.badgeCardNameLocked]}>
                            {badge.name}
                          </Text>
                          <Text style={styles.badgeCardDesc}>{badge.desc}</Text>
                          {isEarned
                            ? <Text style={styles.badgeEarnedTag}>✓ Earned</Text>
                            : <Text style={styles.badgeLockedTag}>Locked</Text>}
                        </View>
                      );
                    })}
                  </View>
                </View>
              );
            })}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
