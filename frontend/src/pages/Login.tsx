import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { useAuth } from "../auth";
import { tokenStore } from "../api/client";
import { PAL } from "../theme";

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => { if (tokenStore.isAuthed()) navigate("/", { replace: true }); }, [navigate]);

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(false);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AxiosError) setError(true);
      else setError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, background: "radial-gradient(120% 90% at 80% -10%, #E4F6F0 0%, #F5F7F6 45%, #F5F7F6 100%)", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", width: 520, height: 520, borderRadius: 999, background: "radial-gradient(circle at center,#CDEFE4 0%,rgba(205,239,228,0) 70%)", top: -160, left: -120, filter: "blur(8px)" }} />
      <div style={{ position: "absolute", width: 420, height: 420, borderRadius: 999, background: "radial-gradient(circle at center,#D9EEE7 0%,rgba(217,238,231,0) 70%)", bottom: -160, right: -80 }} />
      <form onSubmit={submit} style={{ position: "relative", width: "100%", maxWidth: 420, background: "#fff", border: `1px solid ${PAL.border}`, borderRadius: 20, boxShadow: "0 1px 2px rgba(16,40,30,.04),0 24px 60px rgba(16,40,30,.10)", padding: "36px 34px 30px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 26 }}>
          <div style={{ width: 42, height: 42, borderRadius: 13, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 6px 16px rgba(46,158,115,.35)" }}>
            <div style={{ width: 18, height: 18, borderRadius: 999, border: "2.5px solid #fff", position: "relative" }}><div style={{ position: "absolute", width: 5, height: 5, borderRadius: 999, background: "#fff", top: 4, left: 4 }} /></div>
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-.02em", color: "#182628" }}>FB&nbsp;SPY</div>
            <div style={{ fontSize: 11, color: PAL.muted, letterSpacing: ".08em", textTransform: "uppercase", fontWeight: 600 }}>Ad Intelligence Console</div>
          </div>
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 4px", color: PAL.head, letterSpacing: "-.01em" }}>Sign in</h1>
        <p style={{ margin: "0 0 22px", fontSize: 13.5, color: PAL.text2 }}>Internal access only. Use the credentials provided by your admin.</p>

        <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: PAL.text, marginBottom: 6 }}>Username</label>
        <input value={username} onChange={(e) => { setUsername(e.target.value); setError(false); }} placeholder="you@team" style={{ ...field, marginBottom: 16 }} />

        <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: PAL.text, marginBottom: 6 }}>Password</label>
        <div style={{ position: "relative", marginBottom: 8 }}>
          <input value={password} onChange={(e) => { setPassword(e.target.value); setError(false); }} type={showPass ? "text" : "password"} placeholder="••••••••" style={{ ...field, padding: "0 44px 0 14px" }} />
          <button type="button" onClick={() => setShowPass((s) => !s)} style={{ position: "absolute", right: 6, top: 6, height: 32, width: 32, border: "none", background: "transparent", color: PAL.muted, borderRadius: 8, cursor: "pointer", fontSize: 15 }}>{showPass ? "🙈" : "👁"}</button>
        </div>

        {error && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", background: "#FBE2DF", border: "1px solid #F2C2BD", color: "#B23B31", borderRadius: 10, padding: "9px 12px", fontSize: 12.5, fontWeight: 500, marginBottom: 14 }}>
            <span>⚠</span><span>Incorrect username or password.</span>
          </div>
        )}

        <button type="submit" disabled={loading} style={{ width: "100%", height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 9, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", color: "#fff", border: "none", borderRadius: 12, fontSize: 14.5, fontWeight: 600, cursor: "pointer", boxShadow: "0 6px 18px rgba(46,158,115,.32)", opacity: loading ? 0.85 : 1 }}>
          {loading && <span style={{ width: 15, height: 15, border: "2px solid rgba(255,255,255,.5)", borderTopColor: "#fff", borderRadius: 999, display: "inline-block", animation: "fbspySpin .7s linear infinite" }} />}
          <span>{loading ? "Signing in…" : "Sign in"}</span>
        </button>

        <div style={{ marginTop: 18, textAlign: "center", fontSize: 12, color: PAL.muted }}>No account? <span style={{ color: PAL.text2, fontWeight: 500 }}>Contact your admin.</span></div>
      </form>
    </div>
  );
}

const field: CSSProperties = { width: "100%", height: 44, border: `1px solid ${PAL.border}`, borderRadius: 11, padding: "0 14px", fontSize: 14, color: PAL.text, background: "#FBFCFB", outline: "none" };
