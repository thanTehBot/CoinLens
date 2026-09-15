import { useEffect, useState } from "react";
import { View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { isAdminUser, mapSupabaseUser, friendlyAuthError } from "../authLogic";
import { supabase } from "./api/supabase";
import styles from "./theme/styles";
import AuthScreen from "./screens/auth/AuthScreen";
import HomeScreen from "./screens/home/HomeScreen";
import ScanScreen from "./screens/scan/ScanScreen";
import AdminScreen from "./screens/admin/AdminScreen";
import StatsScreen from "./screens/stats/StatsScreen";
import LeaderboardScreen from "./screens/leaderboard/LeaderboardScreen";
import AccountScreen from "./screens/account/AccountScreen";
import BadgesScreen from "./badges/BadgesScreen";

export default function App() {
  const [screen, setScreen] = useState("home");
  const [user, setUser] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [userScans, setUserScans] = useState([]);
  const [isGuest, setIsGuest] = useState(false);

  useEffect(() => {
    let mounted = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setUser(mapSupabaseUser(data.session?.user));
      setAuthReady(true);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      setUser(mapSupabaseUser(session?.user));
    });

    AsyncStorage.getItem("@coinlens_scans")
      .then(data => { if (data) setUserScans(JSON.parse(data)); })
      .catch(() => {});

    return () => {
      mounted = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  async function signUp(name, email, password, role = "member") {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { name, role } },
    });
    if (error) throw new Error(friendlyAuthError(error));
    if (!data.session) {
      throw new Error("Account created. Check your email to confirm it, then sign in.");
    }
  }

  async function signIn(email, password) {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(friendlyAuthError(error));
  }

  async function signOut() {
    await supabase.auth.signOut();
    setScreen("home");
  }

  function continueAsGuest() {
    setIsGuest(true);
    setScreen("scan");
  }

  function exitGuest() {
    setIsGuest(false);
    setScreen("home");
  }

  function navigate(target) { setScreen(target); }

  if (!authReady) return <View style={styles.safeArea} />;

  if (isGuest) {
    return <ScanScreen navigate={(target) => (target === "home" ? exitGuest() : navigate(target))} user={{ name: "Guest" }} />;
  }

  if (!user) return <AuthScreen onSignIn={signIn} onSignUp={signUp} onGuest={continueAsGuest} />;

  if (screen === "home") return <HomeScreen navigate={navigate} />;
  if (screen === "scan") return <ScanScreen navigate={navigate} user={user} />;
  if (screen === "badges") return <BadgesScreen navigate={navigate} user={user} userScans={userScans} />;
  if (screen === "leaderboard") return <LeaderboardScreen navigate={navigate} user={user} userScans={userScans} />;
  if (screen === "account") return <AccountScreen navigate={navigate} user={user} onSignOut={signOut} />;
  if (screen === "admin" && isAdminUser(user)) return <AdminScreen navigate={navigate} />;
  if (screen === "stats") return <StatsScreen key={user.id} navigate={navigate} />;
  return <HomeScreen navigate={navigate} />;
}
