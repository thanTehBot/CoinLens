import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import GoldCoin from "../../components/GoldCoin";
import styles from "../../theme/styles";
import { verifyAdminCode } from "../../api/client";

function PasswordInput({ label, value, onChangeText, autoComplete }) {
  const [visible, setVisible] = useState(false);

  return (
    <View style={styles.passwordField}>
      <TextInput
        style={[styles.input, styles.passwordInput]}
        placeholder={label}
        accessibilityLabel={label}
        placeholderTextColor="rgba(255,215,0,0.35)"
        value={value}
        onChangeText={onChangeText}
        secureTextEntry={!visible}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete={autoComplete}
      />
      <TouchableOpacity
        style={styles.passwordToggle}
        onPress={() => setVisible(current => !current)}
        accessibilityRole="button"
        accessibilityLabel={(visible ? "Hide " : "Show ") + label.toLowerCase()}
      >
        <Text style={styles.passwordToggleText}>{visible ? "Hide" : "Show"}</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function AuthScreen({ onSignIn, onSignUp, onGuest }) {
  const [tab, setTab] = useState("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [adminCode, setAdminCode] = useState("");
  const [showAdminField, setShowAdminField] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [offerSignUp, setOfferSignUp] = useState(false);

  function switchToSignUp() {
    setTab("signup");
    setConfirmPassword("");
    setError("");
    setOfferSignUp(false);
    setShowAdminField(false);
    setAdminCode("");
  }

  async function handleSubmit() {
    setError("");
    setOfferSignUp(false);
    setLoading(true);
    try {
      if (tab === "signup") {
        if (!name.trim()) throw new Error("Username is required.");
        if (!email.trim()) throw new Error("Email is required.");
        if (password.length < 6) throw new Error("Password must be at least 6 characters.");
        if (!confirmPassword) throw new Error("Please confirm your password.");
        if (password !== confirmPassword) throw new Error("Passwords do not match.");
        let role = "member";
        if (adminCode) {
          if (!(await verifyAdminCode(adminCode))) throw new Error("Invalid admin code.");
          role = "admin";
        }
        await onSignUp(name.trim(), email.trim().toLowerCase(), password, role);
      } else {
        if (!email.trim() || !password) throw new Error("Enter your email and password.");
        await onSignIn(email.trim().toLowerCase(), password);
      }
    } catch (e) {
      setError(e.message);
      if (e.message.includes("Email not found")) setOfferSignUp(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.authContainer} keyboardShouldPersistTaps="handled">
          <View style={styles.authLogoRow}>
            <GoldCoin size={52} />
            <Text style={styles.authAppTitle}>CoinLens</Text>
          </View>

          <View style={styles.authTabRow}>
            {["signin", "signup"].map(t => (
              <TouchableOpacity key={t} style={[styles.authTab, tab === t && styles.authTabActive]} onPress={() => { setTab(t); setConfirmPassword(""); setError(""); setShowAdminField(false); setAdminCode(""); }}>
                <Text style={[styles.authTabText, tab === t && styles.authTabTextActive]}>{t === "signin" ? "Sign In" : "Sign Up"}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <View style={styles.authForm}>
            {tab === "signup" && (
              <TextInput style={styles.input} placeholder="Username" placeholderTextColor="rgba(255,215,0,0.35)" value={name} onChangeText={setName} autoCapitalize="none" />
            )}
            <TextInput style={styles.input} placeholder="Email" placeholderTextColor="rgba(255,215,0,0.35)" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" />
            <PasswordInput key={tab} label="Password" value={password} onChangeText={setPassword} autoComplete={tab === "signup" ? "new-password" : "current-password"} />
            {tab === "signup" && (
              <PasswordInput label="Confirm Password" value={confirmPassword} onChangeText={setConfirmPassword} autoComplete="new-password" />
            )}
            {tab === "signup" && (
              showAdminField ? (
                <TextInput style={[styles.input, styles.inputAdmin]} placeholder="Admin code" placeholderTextColor="rgba(255,165,0,0.4)" value={adminCode} onChangeText={setAdminCode} autoCapitalize="none" />
              ) : (
                <TouchableOpacity onPress={() => setShowAdminField(true)}>
                  <Text style={styles.adminCodeToggle}>Have an admin code?</Text>
                </TouchableOpacity>
              )
            )}
            {error ? <Text style={styles.authError}>{error}</Text> : null}
            {offerSignUp ? (
              <TouchableOpacity style={styles.authRecoverBtn} onPress={switchToSignUp}>
                <Text style={styles.authRecoverText}>No account found — create one with this email?</Text>
              </TouchableOpacity>
            ) : null}
            <TouchableOpacity style={styles.primaryBtn} onPress={handleSubmit} disabled={loading}>
              {loading
                ? <ActivityIndicator color="#000" />
                : <Text style={styles.primaryBtnText}>{tab === "signup" ? "Create Account" : "Sign In"}</Text>}
            </TouchableOpacity>
            <TouchableOpacity style={styles.guestBtn} onPress={onGuest}>
              <Text style={styles.guestBtnText}>Use as Guest</Text>
              <Text style={styles.guestBtnSubtext}>Scan a coin without an account — everything else requires signing in.</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
