import { Text, View } from "react-native";
import { GOLD } from "../theme/colors";
import styles from "../theme/styles";

export default function ConfidenceMeter({ value = 0 }) {
  const pct = Math.max(0, Math.min(100, value));
  const color = pct >= 75 ? GOLD : pct >= 45 ? "#FFA500" : "#FF4444";
  const label = pct >= 75 ? "High Confidence" : pct >= 45 ? "Moderate" : "Low Confidence";
  return (
    <View style={styles.resultCard}>
      <Text style={styles.resultCardTitle}>AI Confidence</Text>
      <View style={styles.meterRow}>
        <View style={styles.meterTrack}>
          <View style={[styles.meterFill, { width: `${pct}%`, backgroundColor: color }]} />
        </View>
        <Text style={[styles.meterPct, { color }]}>{pct}%</Text>
      </View>
      <Text style={[styles.meterLabel, { color }]}>{label}</Text>
    </View>
  );
}
