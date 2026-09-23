import { SafeAreaView, ScrollView, Text, TouchableOpacity, View } from "react-native";
import GoldCoin from "../../components/GoldCoin";
import Header from "../../components/Header";
import styles from "../../theme/styles";

export default function HomeScreen({ navigate }) {
  const cards = [
    { label: "Scan Coin", icon: "🔍", screen: "scan", desc: "Guess your coin with AI" },
    { label: "Badges", icon: "🏅", screen: "badges", desc: "View your achievements" },
    { label: "Leaderboard", icon: "🏆", screen: "leaderboard", desc: "See top collectors" },
  ];

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="CoinLens" showCoin onAccount={() => navigate("account")} />
      <ScrollView contentContainerStyle={styles.homeContainer}>
        <Text style={styles.homeGreeting}>What would you like to do?</Text>
        {cards.map(card => (
          <TouchableOpacity key={card.screen} style={styles.card} onPress={() => navigate(card.screen)}>
            <Text style={styles.cardIcon}>{card.icon}</Text>
            <View style={styles.cardText}>
              <Text style={styles.cardLabel}>{card.label}</Text>
              <Text style={styles.cardDesc}>{card.desc}</Text>
            </View>
            <Text style={styles.cardArrow}>›</Text>
          </TouchableOpacity>
        ))}

        <Text style={styles.sectionTitle}>Recently Scanned Coins</Text>
        {[
          { name: "1965 Quarter", detail: "George Washington · Silver-clad" },
          { name: "1982 Penny", detail: "Abraham Lincoln · Zinc/Copper" },
          { name: "2000 Sacagawea Dollar", detail: "Sacagawea · Gold-colored" },
        ].map((coin, i) => (
          <View key={i} style={styles.recentItem}>
            <GoldCoin size={40} />
            <View style={styles.recentText}>
              <Text style={styles.recentName}>{coin.name}</Text>
              <Text style={styles.recentDetail}>{coin.detail}</Text>
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
