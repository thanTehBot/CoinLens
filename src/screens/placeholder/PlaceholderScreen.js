import { SafeAreaView, Text, View } from "react-native";
import GoldCoin from "../../components/GoldCoin";
import Header from "../../components/Header";
import styles from "../../theme/styles";

export default function PlaceholderScreen({ title, icon, navigate }) {
  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title={title} onBack={() => navigate("home")} />
      <View style={styles.center}>
        <GoldCoin size={80} />
        <Text style={styles.pageTitle}>{title}</Text>
        <Text style={styles.pageSubtitle}>Coming soon!</Text>
      </View>
    </SafeAreaView>
  );
}
