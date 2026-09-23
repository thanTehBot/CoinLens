import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Image,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import ConfidenceMeter from "../../components/ConfidenceMeter";
import GoldCoin from "../../components/GoldCoin";
import Header from "../../components/Header";
import { GOLD, BOX_SIZE } from "../../theme/colors";
import styles from "../../theme/styles";
import { getCaptureStageMeta } from "../../../scanFlowLogic";
import {
  ScanError,
  makeErrorDetail,
  identifyCoin,
  toLegacyScanResult,
  generateEbayListing,
} from "../../api/client";
import { prepareImageForIdentification } from "../../api/imagePrep";

// V1: eBay listing generation is out of scope (server also short-circuits
// /api/generate-ebay-listing via ENABLE_EBAY_LISTING). Kept as a single flag,
// not a deletion, so the feature - and the UI below - can come back later.
const EBAY_LISTING_ENABLED = false;

const BLUR_LAYERS = [
  { offset: -20, opacity: 0.05, height: 3 },
  { offset: -11, opacity: 0.18, height: 2 },
  { offset: -5,  opacity: 0.35, height: 2 },
  { offset: 5,   opacity: 0.35, height: 2 },
  { offset: 11,  opacity: 0.18, height: 2 },
  { offset: 20,  opacity: 0.05, height: 3 },
];

export default function ScanScreen({ navigate, user, onScanSaved }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [phase, setPhase] = useState("choose"); // choose | scanning | loading | result | error | unidentifiable
  const [captureStage, setCaptureStage] = useState("front");
  const [frontImage, setFrontImage] = useState(null);
  const [backImage, setBackImage] = useState(null);
  const [loadingStep, setLoadingStep] = useState("");
  const [result, setResult] = useState(null);
  const [errorDetail, setErrorDetail] = useState(null);
  const [ebayListing, setEbayListing] = useState(null);
  const [listingLoading, setListingLoading] = useState(false);
  const [listingError, setListingError] = useState("");
  const [cameraReady, setCameraReady] = useState(false);
  const [flashActive, setFlashActive] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [selectedUpload, setSelectedUpload] = useState(null);
  const scanAnim = useRef(new Animated.Value(0)).current;
  const flashAnim = useRef(new Animated.Value(0)).current;
  const cameraRef = useRef(null);
  const captureMeta = getCaptureStageMeta(captureStage);

  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(scanAnim, { toValue: 1, duration: 1800, useNativeDriver: true }),
        Animated.timing(scanAnim, { toValue: 0, duration: 1800, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, []);

  function startNewScan() {
    setPhase("choose");
    setCaptureStage("front");
    setFrontImage(null);
    setBackImage(null);
    setLoadingStep("");
    setErrorDetail(null);
    setCameraReady(false);
    setIsCapturing(false);
    setEbayListing(null);
    setListingError("");
    setListingLoading(false);
    setSelectedUpload(null);
  }

  async function capturePhoto() {
    try {
      const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.92 });
      if (!photo?.base64) throw new ScanError("photo", "Photo was captured but contained no image data. Try again.");
      return photo;
    } catch {
      throw new ScanError("photo", "Failed to take the photo. Make sure nothing is blocking the camera.");
    }
  }

  async function capture() {
    if (isCapturing) return;
    if (!cameraRef.current) {
      setErrorDetail(makeErrorDetail(new ScanError("camera", "The camera hasn't finished initializing. Wait a moment and try again.")));
      setPhase("error");
      return;
    }
    setIsCapturing(true);
    try {
      setFlashActive(true);
      if (captureStage === "front") {
        setLoadingStep("Capturing the front of the coin...");
        const photo = await capturePhoto();
        setFrontImage(await prepareImageForIdentification(photo));
        setCaptureStage("back");
        setLoadingStep("");
        return;
      }

      if (!frontImage) {
        throw new ScanError("photo", "The front photo is missing. Please capture the front side again.");
      }

      setPhase("loading");
      setLoadingStep("Capturing the back of the coin...");
      const photo = await capturePhoto();
      const backBase64 = await prepareImageForIdentification(photo);
      setBackImage(backBase64);

      setLoadingStep("Identifying the coin from both sides...");
      const coinLensResult = await identifyCoin(frontImage, backBase64, "camera");
      const legacyResult = toLegacyScanResult(coinLensResult);
      const { coinData } = legacyResult;

      if (coinData.identifiable === false) {
        setErrorDetail({ icon: "!", title: "Coin Not Recognized", body: coinData.unidentifiable_reason || "CoinLens could not identify this coin.", tip: null });
        setPhase("unidentifiable");
        return;
      }

      onScanSaved?.();
      setEbayListing(null);
      setListingError("");
      setResult(legacyResult);
      setPhase("result");
    } catch (e) {
      setErrorDetail(makeErrorDetail(e));
      setPhase("error");
    } finally {
      setIsCapturing(false);
    }
  }

  useEffect(() => {
    if (!flashActive) return undefined;
    flashAnim.setValue(0);
    const animation = Animated.sequence([
      Animated.timing(flashAnim, { toValue: 1, duration: 180, useNativeDriver: true }),
      Animated.timing(flashAnim, { toValue: 0, duration: 180, useNativeDriver: true }),
    ]);
    animation.start(() => setFlashActive(false));
    return () => animation.stop();
  }, [flashActive, flashAnim]);

  async function uploadPhoto() {
    const permissionResult = await ImagePicker.requestMediaLibraryPermissionsAsync(false);
    if (!permissionResult.granted) {
      setErrorDetail(makeErrorDetail(new ScanError(
        "permission",
        permissionResult.canAskAgain
          ? "Photo access is needed to upload a coin image. Tap Upload Photo again to retry."
          : "Photo access is blocked. Enable Photos access for CoinLens in your device settings."
      )));
      setPhase("error");
      return;
    }

    const photo = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      allowsMultipleSelection: false,
      base64: true,
      quality: 0.92,
    });

    if (photo.canceled || !photo.assets?.[0]?.base64) {
      return;
    }

    setSelectedUpload(photo.assets[0]);
  }

  async function startUploadedPhotoScan() {
    if (!selectedUpload?.base64) {
      setErrorDetail(makeErrorDetail(new ScanError("photo", "Choose a photo before starting the scan.")));
      setPhase("error");
      return;
    }

    try {
      setPhase("loading");
      setLoadingStep("Identifying the coin...");
      const uploadBase64 = await prepareImageForIdentification(selectedUpload);
      const coinLensResult = await identifyCoin(uploadBase64, null, "gallery");
      const legacyResult = toLegacyScanResult(coinLensResult);
      const { coinData } = legacyResult;

      if (coinData.identifiable === false) {
        setErrorDetail(makeErrorDetail(new ScanError("unidentifiable", coinData.unidentifiable_reason || "Could not identify this coin.")));
        setPhase("unidentifiable");
        return;
      }

      onScanSaved?.();
      setResult(legacyResult);
      setPhase("result");
    } catch (e) {
      setErrorDetail(makeErrorDetail(e));
      setPhase("error");
    }
  }

  if (phase === "choose") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scan Coin" onBack={() => navigate("home")} />
        <ScrollView contentContainerStyle={styles.scanChoiceContainer}>
          <GoldCoin size={88} />
          <Text style={styles.pageTitle}>Scan Coin</Text>
          <Text style={styles.pageSubtitle}>Choose how you want to add a coin photo.</Text>

          <View style={styles.scanChoiceOptions}>
            <TouchableOpacity style={styles.scanChoiceCard} onPress={uploadPhoto}>
              <Text style={styles.scanChoiceIcon}>+</Text>
              <View style={styles.cardText}>
                <Text style={styles.cardLabel}>Upload Photo</Text>
                <Text style={styles.cardDesc}>Pick an existing coin photo</Text>
              </View>
              <Text style={styles.cardArrow}>&gt;</Text>
            </TouchableOpacity>

            {selectedUpload ? (
              <View style={styles.uploadPreviewCard}>
                <Text style={styles.resultCardTitle}>Selected Photo</Text>
                <View style={styles.uploadPreviewFrame}>
                  <Image source={{ uri: selectedUpload.uri }} style={styles.uploadPreviewImage} />
                </View>
                <View style={styles.uploadPreviewActions}>
                  <TouchableOpacity style={styles.secondaryBtn} onPress={uploadPhoto}>
                    <Text style={styles.secondaryBtnText}>Choose Different</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={styles.previewScanBtn} onPress={startUploadedPhotoScan}>
                    <Text style={styles.previewScanBtnText}>Start Scan</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ) : null}

            <TouchableOpacity style={styles.scanChoiceCard} onPress={() => { setCaptureStage("front"); setFrontImage(null); setBackImage(null); setPhase("scanning"); }}>
              <Text style={styles.scanChoiceIcon}>[]</Text>
              <View style={styles.cardText}>
                <Text style={styles.cardLabel}>Take Photo</Text>
                <Text style={styles.cardDesc}>Use your camera for a new scan</Text>
              </View>
              <Text style={styles.cardArrow}>&gt;</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (phase === "scanning" && !permission) return <View style={styles.safeArea} />;

  if (phase === "scanning" && !permission.granted) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scan Coin" onBack={() => setPhase("choose")} />
        <View style={styles.center}>
          <GoldCoin size={80} />
          <Text style={styles.pageTitle}>Camera Access</Text>
          <Text style={styles.pageSubtitle}>Camera access is needed to scan your coins.</Text>
          <TouchableOpacity style={styles.primaryBtn} onPress={requestPermission}>
            <Text style={styles.primaryBtnText}>Allow Camera</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  if (phase === "loading") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scan Coin" onBack={() => setPhase("choose")} />
        <View style={styles.center}>
          <ActivityIndicator size="large" color={GOLD} />
          <Text style={styles.loadingStep}>{loadingStep}</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (phase === "error") {
    const ed = errorDetail ?? { icon: "!", title: "Something Went Wrong", body: "An unexpected error occurred.", tip: "Try scanning again.", retryable: true };
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scan Coin" onBack={() => navigate("home")} />
        <View style={styles.center}>
          <Text style={styles.errorIcon}>{ed.icon}</Text>
          <Text style={styles.pageTitle}>{ed.title}</Text>
          <Text style={styles.errorBody}>{ed.body}</Text>
          {ed.tip ? (
            <View style={styles.errorTipBox}>
              <Text style={styles.errorTipLabel}>What to do</Text>
              <Text style={styles.errorTipText}>{ed.tip}</Text>
            </View>
          ) : null}
          {ed.retryable === false ? (
            <TouchableOpacity style={styles.primaryBtn} onPress={() => { startNewScan(); navigate("home"); }}>
              <Text style={styles.primaryBtnText}>Back to Home</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity style={styles.primaryBtn} onPress={startNewScan}>
              <Text style={styles.primaryBtnText}>Try Again</Text>
            </TouchableOpacity>
          )}
        </View>
      </SafeAreaView>
    );
  }

  if (phase === "unidentifiable") {
    const ed = errorDetail ?? { icon: "!", title: "Coin Not Recognized", body: "CoinLens could not identify this coin.", tip: null };
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Scan Coin" onBack={() => navigate("home")} />
        <View style={styles.center}>
          <Text style={styles.errorIcon}>{ed.icon}</Text>
          <Text style={styles.pageTitle}>{ed.title}</Text>
          <Text style={styles.errorBody}>{ed.body}</Text>
          <View style={styles.unidentifiableTips}>
            <Text style={styles.tipsTitle}>Tips for a better scan</Text>
            {["Place the coin on a flat, dark surface", "Use good lighting - avoid glare", "Hold the camera steady and close", "Make sure the full coin is in frame"].map((tip, i) => (
              <Text key={i} style={styles.tipItem}>- {tip}</Text>
            ))}
          </View>
          <TouchableOpacity style={styles.primaryBtn} onPress={startNewScan}>
            <Text style={styles.primaryBtnText}>Try Again</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  async function handleCreateEbayListing() {
    if (!result) return;

    setListingLoading(true);
    setListingError("");
    try {
      const { coinData, numistaData, valueEstimate, summary } = result;
      const listing = await generateEbayListing(coinData, numistaData, valueEstimate, summary);
      if (!listing) throw new Error("Unable to generate the listing draft right now.");
      setEbayListing(listing);
    } catch (err) {
      setListingError(err.message || "Unable to create the listing draft.");
    } finally {
      setListingLoading(false);
    }
  }

  if (phase === "result" && result) {
    const { coinData, numistaData, pcgsData, valueEstimate, summary } = result;
    return (
      <SafeAreaView style={styles.safeArea}>
        <Header title="Coin Identified" onBack={startNewScan} />
        <ScrollView contentContainerStyle={styles.resultContainer}>
          <GoldCoin size={72} />
          <Text style={styles.resultCoinName}>
            {coinData.year !== "Unknown" ? `${coinData.year} ` : ""}{coinData.country} {coinData.denomination}
          </Text>

          <ConfidenceMeter value={coinData.confidence} />

          {Array.isArray(coinData.alternatives) && coinData.alternatives.length > 0 && (
            <View style={styles.resultCard}>
              <Text style={styles.resultCardTitle}>Could Also Be</Text>
              {coinData.alternatives.map((alt, i) => (
                <View key={i} style={styles.altRow}>
                  <View style={styles.altInfo}>
                    <Text style={styles.altCoin}>{alt.coin}</Text>
                    <View style={styles.altBarTrack}>
                      <View style={[styles.altBarFill, { width: `${alt.confidence}%` }]} />
                    </View>
                  </View>
                  <Text style={styles.altPct}>{alt.confidence}%</Text>
                </View>
              ))}
            </View>
          )}

          <View style={styles.resultCard}>
            <Text style={styles.resultCardTitle}>AI Identification</Text>
            {[["Country", coinData.country], ["Denomination", coinData.denomination],
              ["Year", coinData.year], ["Mint Mark", coinData.mint_mark],
              ["Grade", coinData.estimated_grade],
              ["Varieties", coinData.varieties]].map(([label, val]) =>
              val && val !== "Unknown" ? (
                <View key={label} style={styles.resultRow}>
                  <Text style={styles.resultLabel}>{label}</Text>
                  <Text style={styles.resultValue}>{val}</Text>
                </View>
              ) : null
            )}
            {coinData.special_notes ? (
              <Text style={[styles.resultSummary, { marginTop: 4 }]}>{coinData.special_notes}</Text>
            ) : null}
          </View>

          {coinData.mint_errors?.length > 0 && (
            <View style={[styles.resultCard, styles.errorCard]}>
              <Text style={[styles.resultCardTitle, { color: "#FF6B35" }]}>Mint Errors Detected</Text>
              {coinData.mint_errors.map((err, i) => (
                <View key={i} style={styles.errorRow}>
                  <Text style={styles.errorBullet}>-</Text>
                  <Text style={styles.errorText}>{err}</Text>
                </View>
              ))}
            </View>
          )}

          {numistaData && !numistaData.error && (
            <View style={styles.resultCard}>
              <Text style={styles.resultCardTitle}>Numista Specs</Text>
              {[["Title", numistaData.title], ["Composition", numistaData.composition?.text],
                ["Weight", numistaData.weight ? `${numistaData.weight}g` : null],
                ["Diameter", numistaData.size ? `${numistaData.size}mm` : null]].map(([label, val]) =>
                val ? (
                  <View key={label} style={styles.resultRow}>
                    <Text style={styles.resultLabel}>{label}</Text>
                    <Text style={styles.resultValue}>{val}</Text>
                  </View>
                ) : null
              )}
            </View>
          )}

          {valueEstimate && (
            <View style={styles.resultCard}>
              <Text style={styles.resultCardTitle}>Estimated Value</Text>
              {valueEstimate.low != null && valueEstimate.high != null ? (
                <View style={styles.valueRangeRow}>
                  <View style={styles.valueBox}>
                    <Text style={styles.valueBoxLabel}>Low</Text>
                    <Text style={styles.valueBoxAmount}>${valueEstimate.low.toLocaleString()}</Text>
                  </View>
                  <Text style={styles.valueDash}>-</Text>
                  <View style={styles.valueBox}>
                    <Text style={styles.valueBoxLabel}>High</Text>
                    <Text style={styles.valueBoxAmount}>${valueEstimate.high.toLocaleString()}</Text>
                  </View>
                </View>
              ) : (
                <View style={styles.valueRangeRow}>
                  <View style={styles.valueBox}>
                    <Text style={styles.valueBoxLabel}>{valueEstimate.currency || "USD"}</Text>
                    <Text style={styles.valueBoxAmount}>
                      {valueEstimate.estimated_value != null ? `$${valueEstimate.estimated_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "-"}
                    </Text>
                  </View>
                </View>
              )}
              {valueEstimate.source ? (
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>Source</Text>
                  <Text style={styles.resultValue}>{valueEstimate.source}</Text>
                </View>
              ) : null}
              {valueEstimate.condition_assumed ? (
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>Condition assumed</Text>
                  <Text style={styles.resultValue}>{valueEstimate.condition_assumed}</Text>
                </View>
              ) : null}
              {valueEstimate.error_value_note ? (
                <Text style={[styles.resultSummary, { color: "#FF6B35", fontWeight: "700" }]}>{valueEstimate.error_value_note}</Text>
              ) : null}
              {valueEstimate.reasoning ? (
                <Text style={styles.resultSummary}>{valueEstimate.reasoning}</Text>
              ) : null}
            </View>
          )}

          {(!valueEstimate) && (
            <View style={styles.resultCard}>
              <Text style={styles.resultCardTitle}>Estimated Value</Text>
              <Text style={styles.resultSummary}>Not available for this coin and grade yet.</Text>
            </View>
          )}

          {pcgsData && !pcgsData.error && (
            <View style={styles.resultCard}>
              <Text style={styles.resultCardTitle}>PCGS Value</Text>
              {[["Grade", pcgsData.grade], ["Price", pcgsData.price ? `$${pcgsData.price}` : null],
                ["Designation", pcgsData.designation]].map(([label, val]) =>
                val ? (
                  <View key={label} style={styles.resultRow}>
                    <Text style={styles.resultLabel}>{label}</Text>
                    <Text style={styles.resultValue}>{val}</Text>
                  </View>
                ) : null
              )}
            </View>
          )}

          <View style={styles.resultCard}>
            <Text style={styles.resultCardTitle}>Summary</Text>
            <Text style={styles.resultSummary}>{summary}</Text>
          </View>

          {EBAY_LISTING_ENABLED && (
            <View style={styles.resultCard}>
              <Text style={styles.resultCardTitle}>eBay Listing Draft</Text>
              {ebayListing ? (
                <>
                  <Text style={styles.resultSummary}><Text style={styles.resultLabel}>Title: </Text>{ebayListing.title}</Text>
                  {ebayListing.subtitle ? <Text style={styles.resultSummary}><Text style={styles.resultLabel}>Subtitle: </Text>{ebayListing.subtitle}</Text> : null}
                  {ebayListing.description ? <Text style={styles.resultSummary}>{ebayListing.description}</Text> : null}
                  {Array.isArray(ebayListing.item_specifics) && ebayListing.item_specifics.length > 0 ? (
                    <View style={styles.listingSpecList}>
                      {ebayListing.item_specifics.map((spec, i) => (
                        <View key={`${spec.label}-${i}`} style={styles.listingSpecRow}>
                          <Text style={styles.resultLabel}>{spec.label}</Text>
                          <Text style={styles.resultValue}>{spec.value}</Text>
                        </View>
                      ))}
                    </View>
                  ) : null}
                  {ebayListing.shipping_notes ? <Text style={styles.resultSummary}>Shipping notes: {ebayListing.shipping_notes}</Text> : null}
                </>
              ) : (
                <Text style={styles.resultSummary}>Create a polished eBay title, description, item specifics, and shipping notes for this coin.</Text>
              )}
              {listingError ? <Text style={styles.authError}>{listingError}</Text> : null}
              <TouchableOpacity style={[styles.secondaryBtn, listingLoading && styles.secondaryBtnDisabled]} onPress={handleCreateEbayListing} disabled={listingLoading}>
                {listingLoading ? <ActivityIndicator color="#000" /> : <Text style={styles.secondaryBtnText}>{ebayListing ? "Refresh eBay Listing" : "Create Ideal eBay Listing"}</Text>}
              </TouchableOpacity>
            </View>
          )}

          <TouchableOpacity style={styles.primaryBtn} onPress={startNewScan}>
            <Text style={styles.primaryBtnText}>Scan Another</Text>
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // Scanning view
  return (
    <SafeAreaView style={styles.safeArea}>
      <Header title="Scan Coin" onBack={() => navigate("home")} />
      <View style={styles.scannerOuter}>
        <View style={styles.scannerBoxWrapper}>
          <View style={styles.scannerBox}>
            <CameraView ref={cameraRef} style={StyleSheet.absoluteFill} facing="back" zoom={0.3} onCameraReady={() => setCameraReady(true)} />
            <View style={[styles.corner, styles.cornerTL]} />
            <View style={[styles.corner, styles.cornerTR]} />
            <View style={[styles.corner, styles.cornerBL]} />
            <View style={[styles.corner, styles.cornerBR]} />
            {BLUR_LAYERS.map(({ offset, opacity, height }, i) => (
              <Animated.View key={i} style={{
                position: "absolute", left: 0, right: 0, height,
                backgroundColor: GOLD, opacity,
                transform: [{ translateY: scanAnim.interpolate({
                  inputRange: [0, 1], outputRange: [offset, BOX_SIZE - 3 + offset],
                })}],
              }} />
            ))}
            <Animated.View style={[styles.scanLineSolid, {
              position: "absolute", left: 0, right: 0,
              transform: [{ translateY: scanAnim.interpolate({
                inputRange: [0, 1], outputRange: [0, BOX_SIZE - 3],
              })}],
            }]} />
          </View>
        </View>
        <Text style={styles.scanHint}>{captureMeta.title}</Text>
        <Text style={styles.scanSubHint}>{captureMeta.body}</Text>
        <TouchableOpacity
          onPress={capture}
          disabled={!cameraReady || isCapturing}
          activeOpacity={0.7}
          accessibilityRole="button"
          accessibilityLabel={captureStage === "front" ? "Capture front of coin" : "Capture back of coin"}
        >
          <Animated.View style={[
            styles.captureIndicator,
            (!cameraReady || isCapturing) && styles.captureIndicatorDisabled,
            flashActive && {
              transform: [{ scale: flashAnim.interpolate({ inputRange: [0, 1], outputRange: [1, 1.18] }) }],
              backgroundColor: flashAnim.interpolate({ inputRange: [0, 1], outputRange: ["rgba(255,215,0,0.08)", GOLD] }),
              borderColor: flashAnim.interpolate({ inputRange: [0, 1], outputRange: ["rgba(255,215,0,0.25)", "#fff6b0"] }),
            },
          ]}>
            <View style={styles.captureButtonInner} />
          </Animated.View>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}
