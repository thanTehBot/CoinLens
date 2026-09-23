import { useEffect, useRef, useState } from "react";
import * as ImagePicker from "expo-image-picker";
import {
  Image,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View
} from "react-native";


// ─── Gold coin component ──────────────────────────────────────────────────────

function GoldCoin({ size = 80 }) {
  return (
    <View style={[styles.goldCoin, { width: size, height: size, borderRadius: size / 2 }]}>
      <Text style={[styles.goldCoinText, { fontSize: size * 0.45 }]}>$</Text>
    </View>
  );
}

// ─── Shared header ────────────────────────────────────────────────────────────

function Header({ title, onBack, onAccount, showCoin }) {
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

// ─── Screens ─────────────────────────────────────────────────────────────────

function HomeScreen({ navigate }) {
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


function PlaceholderScreen({ title, icon, navigate }) {
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

function ScanScreen({ navigate }) {
  const [selectedPhoto, setSelectedPhoto] = useState(null);
  const [pickerError, setPickerError] = useState("");
  const [scanStatus, setScanStatus] = useState("ready");
  const [scanResult, setScanResult] = useState(null);
  const scanTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (scanTimerRef.current) {
        clearTimeout(scanTimerRef.current);
      }
    };
  }, []);

  async function choosePhoto() {
    setPickerError("");

    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setPickerError("Photo access is needed to upload a coin image.");
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      allowsMultipleSelection: false,
      quality: 0.85,
    });

    if (!result.canceled && result.assets?.length) {
      setSelectedPhoto(result.assets[0]);
      setScanStatus("ready");
      setScanResult(null);
    }
  }

  function removePhoto() {
    setSelectedPhoto(null);
    setScanStatus("ready");
    setScanResult(null);
  }

  function resetToUpload() {
    if (scanTimerRef.current) {
      clearTimeout(scanTimerRef.current);
    }
    setScanStatus("ready");
    setScanResult(null);
  }

  function startScan() {
    if (!selectedPhoto) return;

    if (scanTimerRef.current) {
      clearTimeout(scanTimerRef.current);
    }

    setScanStatus("loading");
    setScanResult(null);

    scanTimerRef.current = setTimeout(() => {
      const nextResult = MOCK_SCAN_RESULTS[Math.floor(Math.random() * MOCK_SCAN_RESULTS.length)];
      setScanResult(nextResult);
      setScanStatus("result");
      scanTimerRef.current = null;
    }, 3000);
  }

  if (scanStatus === "loading") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scanning" onBack={() => navigate("home")} />
        <View style={styles.loadingContainer}>
          <View style={styles.loadingCoinWrap}>
            <GoldCoin size={96} />
          </View>
          <Text style={styles.pageTitle}>Scanning Coin</Text>
          <Text style={[styles.pageSubtitle, styles.scanSubtitle]}>
            Analyzing the image and matching visible coin details.
          </Text>
          <View style={styles.loadingBar}>
            <View style={styles.loadingBarFill} />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  if (scanStatus === "result" && selectedPhoto && scanResult) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scan Result" onBack={resetToUpload} />
        <ScrollView contentContainerStyle={styles.resultContainer}>
          <Text style={styles.resultSectionTitle}>Your Photo</Text>
          <View style={styles.resultImageFrame}>
            <Image source={{ uri: selectedPhoto.uri }} style={styles.resultImage} />
          </View>

          <View style={styles.resultGuessRow}>
            <Text style={styles.resultGuess}>{scanResult.coin}</Text>
            <Text style={styles.resultConfidence}>{scanResult.confidence}% confidence</Text>
          </View>

          <Text style={styles.resultDescription}>{scanResult.description}</Text>

          <Text style={styles.resultSectionTitle}>Reference Image</Text>
          <View style={styles.referenceImageFrame}>
            <Image source={{ uri: scanResult.referenceImage }} style={styles.referenceImage} />
          </View>

          <Text style={styles.resultSectionTitle}>Other Possible Matches</Text>
          {OTHER_POSSIBLE_MATCHES.map(match => (
            <View key={match.coin} style={styles.possibleMatch}>
              <View style={styles.possibleMatchHeader}>
                <Text style={styles.possibleMatchName}>{match.coin}</Text>
                <Text style={styles.possibleMatchPercent}>{match.confidence}% match</Text>
              </View>
              <View style={styles.possibleMatchImageFrame}>
                <Image source={{ uri: match.referenceImage }} style={styles.possibleMatchImage} />
              </View>
            </View>
          ))}
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Scan Coin" onBack={() => navigate("home")} />
      <ScrollView contentContainerStyle={styles.scanContainer}>
        <GoldCoin size={88} />
        <Text style={styles.pageTitle}>Scan Coin</Text>
        <Text style={[styles.pageSubtitle, styles.scanSubtitle]}>
          Choose how you want to add a coin photo.
        </Text>

        <View style={styles.scanOptions}>
          <View style={[styles.scanOption, styles.uploadOption]}>
            <TouchableOpacity style={styles.uploadOptionHeader} onPress={choosePhoto}>
              <Text style={styles.scanOptionIcon}>+</Text>
              <View style={styles.cardText}>
                <Text style={styles.cardLabel}>Upload Photo</Text>
                <Text style={styles.cardDesc}>Pick an existing coin photo</Text>
              </View>
              <Text style={styles.cardArrow}>›</Text>
            </TouchableOpacity>

            {pickerError ? <Text style={styles.pickerError}>{pickerError}</Text> : null}

            {selectedPhoto && (
              <View style={styles.selectedPhotoArea}>
                <Pressable style={styles.photoPreview} onPress={removePhoto}>
                  {({ hovered }) => (
                    <>
                      <Image source={{ uri: selectedPhoto.uri }} style={styles.photoPreviewImage} />
                      <View style={[styles.deletePhotoBadge, hovered && styles.deletePhotoBadgeHover]}>
                        <Text style={[styles.deletePhotoText, hovered && styles.deletePhotoTextHover]}>
                          x
                        </Text>
                      </View>
                    </>
                  )}
                </Pressable>

                <TouchableOpacity style={styles.beginScanButton} onPress={startScan}>
                  <Text style={styles.beginScanButtonText}>Start Scan</Text>
                </TouchableOpacity>
              </View>
            )}
          </View>

          <TouchableOpacity style={styles.scanOption}>
            <Text style={styles.scanOptionIcon}>[]</Text>
            <View style={styles.cardText}>
              <Text style={styles.cardLabel}>Take Photo</Text>
              <Text style={styles.cardDesc}>Use your camera for a new scan</Text>
            </View>
            <Text style={styles.cardArrow}>›</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function AccountScreen({ navigate }) {
  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Account" onBack={() => navigate("home")} />
      <View style={styles.center}>
        <View style={styles.avatarCircle}>
          <Text style={styles.avatarText}>👤</Text>
        </View>
        <Text style={styles.pageTitle}>My Account</Text>
        <Text style={styles.pageSubtitle}>Account features coming soon!</Text>
      </View>
    </SafeAreaView>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [screen, setScreen] = useState("home");

  function navigate(target) {
    setScreen(target);
  }

  if (screen === "home") return <HomeScreen navigate={navigate} />;
  if (screen === "scan") return <ScanScreen navigate={navigate} />;
  if (screen === "badges") return <PlaceholderScreen title="Badges" icon="🏅" navigate={navigate} />;
  if (screen === "leaderboard") return <PlaceholderScreen title="Leaderboard" icon="🏆" navigate={navigate} />;
  if (screen === "account") return <AccountScreen navigate={navigate} />;
  return <HomeScreen navigate={navigate} />;
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const GOLD = "#FFD700";
const GOLD_DIM = "rgba(255,215,0,0.15)";
const GOLD_GLOW = {
  shadowColor: GOLD,
  shadowOffset: { width: 0, height: 0 },
  shadowOpacity: 0.75,
  shadowRadius: 12,
  elevation: 10,
};

const MOCK_SCAN_RESULTS = [
  {
    coin: "1982 Lincoln Cent",
    confidence: 87,
    description:
      "A Lincoln cent from 1982, the transition year when U.S. pennies shifted from mostly copper to copper-plated zinc. The obverse shows Abraham Lincoln, while the reverse commonly shows the Lincoln Memorial.",
    referenceImage:
      "https://commons.wikimedia.org/wiki/Special:FilePath/1982_zinc_large_date_Lincoln_cent.png",
  },
  {
    coin: "Washington Quarter",
    confidence: 82,
    description:
      "A Washington quarter features George Washington on the front and an eagle or commemorative design on the back, depending on the year. Modern quarters are usually copper-nickel clad rather than silver.",
    referenceImage:
      "https://commons.wikimedia.org/wiki/Special:FilePath/1968%20US%20Washington%20Quarter%20Denver%20Mint%20(5192662525).jpg",
  },
  {
    coin: "Sacagawea Dollar",
    confidence: 78,
    description:
      "The Sacagawea dollar is a gold-colored U.S. dollar coin first issued in 2000. It is known for its manganese-brass outer layer and its portrait of Sacagawea with her child.",
    referenceImage:
      "https://www.usmint.gov/sites/default/files/styles/coin_large/public/coin-images/2025-sg-proof-obverse.png",
  },
];

const OTHER_POSSIBLE_MATCHES = [
  {
    coin: "Roosevelt Dime",
    confidence: 64,
    referenceImage:
      "https://commons.wikimedia.org/wiki/Special:FilePath/Dime_Obverse_13.png",
  },
  {
    coin: "Jefferson Nickel",
    confidence: 51,
    referenceImage:
      "https://commons.wikimedia.org/wiki/Special:FilePath/United%20States%20nickel%20obverse.jpg",
  },
  {
    coin: "Kennedy Half Dollar",
    confidence: 43,
    referenceImage:
      "https://commons.wikimedia.org/wiki/Special:FilePath/S_Half_Dollar_Obverse_2016.jpg",
  },
];

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#000" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  container: { padding: 24, alignItems: "center", gap: 16, paddingBottom: 40 },

  // Header
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,215,0,0.2)"
  },
  headerSide: { width: 72 },
  headerTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  headerTitle: { fontSize: 18, fontWeight: "700", color: GOLD, textAlign: "center" },
  backBtn: { fontSize: 17, color: GOLD, fontWeight: "600" },
  accountBtn: {
    alignSelf: "flex-end",
    backgroundColor: GOLD_DIM,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: GOLD,
    width: 38,
    height: 38,
    alignItems: "center",
    justifyContent: "center",
    ...GOLD_GLOW,
  },
  accountBtnText: { fontSize: 20 },

  // Home
  homeContainer: { padding: 24, gap: 16, paddingBottom: 40 },
  homeGreeting: { fontSize: 22, fontWeight: "700", color: GOLD, marginBottom: 4 },
  card: {
    backgroundColor: "#0f0f0f",
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.4)",
    padding: 20,
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
    ...GOLD_GLOW,
  },
  cardIcon: { fontSize: 36 },
  cardText: { flex: 1 },
  cardLabel: { fontSize: 20, fontWeight: "700", color: GOLD },
  cardDesc: { fontSize: 14, color: "rgba(255,215,0,0.6)", marginTop: 2 },
  cardArrow: { fontSize: 28, color: "rgba(255,215,0,0.4)", fontWeight: "300" },

  // Recently scanned
  sectionTitle: { fontSize: 16, fontWeight: "700", color: "rgba(255,215,0,0.5)", letterSpacing: 1, marginTop: 8 },
  recentItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    backgroundColor: "#0f0f0f",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.2)",
    padding: 12,
  },
  recentText: { flex: 1 },
  recentName: { fontSize: 16, fontWeight: "700", color: GOLD },
  recentDetail: { fontSize: 13, color: "rgba(255,215,0,0.5)", marginTop: 2 },

  // Shared
  bigIcon: { fontSize: 80, textAlign: "center" },
  pageTitle: { fontSize: 32, fontWeight: "800", color: GOLD, marginTop: 8 },
  pageSubtitle: { fontSize: 17, color: "rgba(255,215,0,0.7)", textAlign: "center", marginTop: 10, lineHeight: 24 },
  primaryBtn: {
    marginTop: 28,
    backgroundColor: GOLD,
    paddingHorizontal: 48,
    paddingVertical: 16,
    borderRadius: 32,
    ...GOLD_GLOW,
  },
  primaryBtnText: { fontSize: 18, fontWeight: "700", color: "#000" },

  // Scan
  scanContainer: {
    flexGrow: 1,
    alignItems: "center",
    padding: 24,
    paddingTop: 40,
    paddingBottom: 40,
  },
  scanSubtitle: {
    maxWidth: 320,
  },
  scanOptions: {
    width: "100%",
    maxWidth: 440,
    gap: 16,
    marginTop: 32,
  },
  scanOption: {
    backgroundColor: "#0f0f0f",
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.4)",
    padding: 20,
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
    ...GOLD_GLOW,
  },
  scanOptionIcon: {
    width: 42,
    fontSize: 32,
    color: GOLD,
    fontWeight: "800",
    textAlign: "center",
  },
  uploadOption: {
    flexDirection: "column",
    alignItems: "stretch",
  },
  uploadOptionHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
  },
  pickerError: {
    color: "#ffb4a8",
    fontSize: 13,
    lineHeight: 18,
    marginTop: 14,
  },
  selectedPhotoArea: {
    marginTop: 18,
    gap: 14,
  },
  photoPreview: {
    height: 190,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.3)",
    overflow: "hidden",
    backgroundColor: "#050505",
  },
  photoPreviewImage: {
    width: "100%",
    height: "100%",
    resizeMode: "contain",
  },
  deletePhotoBadge: {
    position: "absolute",
    top: 10,
    right: 10,
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.75)",
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.6)",
  },
  deletePhotoBadgeHover: {
    backgroundColor: "rgba(255,215,0,0.95)",
  },
  deletePhotoText: {
    color: GOLD,
    fontSize: 18,
    fontWeight: "800",
    lineHeight: 20,
  },
  deletePhotoTextHover: {
    color: "#000",
  },
  beginScanButton: {
    minHeight: 48,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: GOLD,
    ...GOLD_GLOW,
  },
  beginScanButtonText: {
    color: "#000",
    fontSize: 16,
    fontWeight: "800",
  },
  loadingContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  loadingCoinWrap: {
    marginBottom: 8,
  },
  loadingBar: {
    width: "100%",
    maxWidth: 280,
    height: 8,
    borderRadius: 4,
    backgroundColor: "rgba(255,215,0,0.16)",
    overflow: "hidden",
    marginTop: 30,
  },
  loadingBarFill: {
    width: "72%",
    height: "100%",
    borderRadius: 4,
    backgroundColor: GOLD,
  },
  resultContainer: {
    padding: 24,
    paddingBottom: 44,
    gap: 16,
  },
  resultSectionTitle: {
    width: "100%",
    maxWidth: 440,
    alignSelf: "center",
    fontSize: 14,
    fontWeight: "800",
    color: "rgba(255,215,0,0.55)",
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  resultImageFrame: {
    width: "100%",
    maxWidth: 440,
    alignSelf: "center",
    height: 240,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.35)",
    backgroundColor: "#050505",
    overflow: "hidden",
  },
  resultImage: {
    width: "100%",
    height: "100%",
    resizeMode: "contain",
  },
  resultGuessRow: {
    width: "100%",
    maxWidth: 440,
    alignSelf: "center",
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
    marginTop: 4,
  },
  resultGuess: {
    flex: 1,
    color: GOLD,
    fontSize: 24,
    fontWeight: "900",
  },
  resultConfidence: {
    color: "rgba(255,215,0,0.72)",
    fontSize: 14,
    fontWeight: "800",
  },
  resultDescription: {
    width: "100%",
    maxWidth: 440,
    alignSelf: "center",
    color: "rgba(255,215,0,0.76)",
    fontSize: 15,
    lineHeight: 22,
  },
  referenceImageFrame: {
    width: "100%",
    maxWidth: 440,
    alignSelf: "center",
    height: 220,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.3)",
    backgroundColor: "#050505",
    overflow: "hidden",
  },
  referenceImage: {
    width: "100%",
    height: "100%",
    resizeMode: "contain",
  },
  possibleMatch: {
    width: "100%",
    maxWidth: 440,
    alignSelf: "center",
    gap: 10,
    marginTop: 2,
  },
  possibleMatchHeader: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
  },
  possibleMatchName: {
    flex: 1,
    color: GOLD,
    fontSize: 18,
    fontWeight: "800",
  },
  possibleMatchPercent: {
    color: "rgba(255,215,0,0.68)",
    fontSize: 13,
    fontWeight: "800",
  },
  possibleMatchImageFrame: {
    height: 150,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "rgba(255,215,0,0.25)",
    backgroundColor: "#050505",
    overflow: "hidden",
  },
  possibleMatchImage: {
    width: "100%",
    height: "100%",
    resizeMode: "contain",
  },

  // Gold coin
  goldCoin: {
    backgroundColor: GOLD,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: GOLD,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 20,
    elevation: 16,
    borderWidth: 3,
    borderColor: "#FFF8DC",
  },
  goldCoinText: {
    fontWeight: "900",
    color: "#7A5C00",
  },

  // Account
  avatarCircle: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: GOLD_DIM,
    borderWidth: 2,
    borderColor: GOLD,
    alignItems: "center",
    justifyContent: "center",
    ...GOLD_GLOW,
  },
  avatarText: { fontSize: 48 },
});
