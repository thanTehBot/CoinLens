import { useState } from "react";
import {
  ActivityIndicator,
  Button,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View
} from "react-native";
import { identifyCoin } from "./coinIdentifier";

export default function App() {
  const [inputText, setInputText] = useState("");
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  function handleIdentify() {
    setIsLoading(true);

    setTimeout(() => {
      setResult(identifyCoin(inputText));
      setIsLoading(false);
    }, 600);
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.title}>CoinLens Test</Text>
        <Text style={styles.text}>
          Enter a coin clue like quarter, 25 cents, penny, lincoln, nickel, dime, or wheat.
        </Text>

        <TextInput
          style={styles.input}
          value={inputText}
          onChangeText={setInputText}
          placeholder="Type a coin clue"
          autoCapitalize="none"
        />

        <Button
          title={isLoading ? "Identifying..." : "Identify coin"}
          onPress={handleIdentify}
          disabled={isLoading}
        />

        {isLoading ? <ActivityIndicator style={styles.loading} /> : null}

        {result ? (
          <View style={styles.result}>
            <Text style={styles.coinName}>{result.coinName}</Text>
            <Text style={styles.text}>
              Confidence: {Math.round(result.confidenceScore * 100)}%
            </Text>
            <Text style={styles.text}>
              Match type: {result.matchedByKeyword ? "Keyword match" : "Random fallback"}
            </Text>
            <Text style={styles.text}>Description: {result.description}</Text>
            <Text style={styles.text}>History: {result.historyFact}</Text>
            <Text style={styles.text}>
              Alternatives: {result.alternatives.join(", ")}
            </Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#fff"
  },
  container: {
    padding: 20,
    gap: 14
  },
  title: {
    fontSize: 28,
    fontWeight: "700"
  },
  input: {
    borderWidth: 1,
    borderColor: "#aaa",
    borderRadius: 6,
    padding: 12,
    fontSize: 16
  },
  loading: {
    marginTop: 10
  },
  result: {
    marginTop: 16,
    gap: 8
  },
  coinName: {
    fontSize: 22,
    fontWeight: "700"
  },
  text: {
    fontSize: 16,
    lineHeight: 22
  }
});
