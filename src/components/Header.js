import { Text, TouchableOpacity, View } from "react-native";
import GoldCoin from "./GoldCoin";
import styles from "../theme/styles";

export default function Header({ title, onBack, onAccount, showCoin }) {
  return (
    <View style={styles.header}>
      {onBack ? (
        <TouchableOpacity onPress={onBack} style={styles.headerSide}>
          <Text style={styles.backBtn}>‹ Back</Text>
        </TouchableOpacity>
      ) : (
        <View style={styles.headerSide} />
      )}
      <View style={styles.headerTitleRow}>
        {showCoin && <GoldCoin size={28} />}
        <Text style={styles.headerTitle}>{title}</Text>
      </View>
      <View style={styles.headerSide}>
        {onAccount && (
          <TouchableOpacity onPress={onAccount} style={styles.accountBtn}>
            <Text style={styles.accountBtnText}>👤</Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
}
