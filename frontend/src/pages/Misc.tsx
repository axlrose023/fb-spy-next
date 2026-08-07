import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { PAL } from "../theme";

const primary: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 7, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", color: "#fff", border: "none", borderRadius: 11, padding: "10px 18px", fontSize: 13.5, fontWeight: 600, cursor: "pointer", boxShadow: "0 4px 14px rgba(46,158,115,.32)" };

function State({ code, color, title, sub }: { code: string; color: string; title: string; sub: string }) {
  const navigate = useNavigate();
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "calc(100vh - 64px)", textAlign: "center", padding: 40 }}>
      <div style={{ fontSize: 64, fontWeight: 800, color, letterSpacing: "-.04em" }}>{code}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: PAL.head, margin: "8px 0 6px" }}>{title}</div>
      <div style={{ fontSize: 13.5, color: PAL.text2, maxWidth: 340, marginBottom: 20 }}>{sub}</div>
      <button onClick={() => navigate("/")} style={primary}>Back to Ad Library</button>
    </div>
  );
}

export function Forbidden() {
  return <State code="403" color={PAL.danger} title="Access denied" sub="You don’t have permission to view this area. The Users section is admin‑only." />;
}

export function NotFound() {
  return <State code="404" color={PAL.muted} title="Page not found" sub="That ad or page doesn’t exist or may have been removed." />;
}
