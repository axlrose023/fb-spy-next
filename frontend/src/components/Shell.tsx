import { createContext, useContext, useEffect, useState, type CSSProperties } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useUrlFilters } from "../useUrlFilters";
import { PAL, MONO } from "../theme";
import { mono } from "../lib/media";
import { useIsNarrow } from "../lib/responsive";
import UserDrawer from "./UserDrawer";
import DebouncedInput from "./DebouncedInput";

/* Library publishes its total here so the top bar can show the count without refetching. */
const CountCtx = createContext<{ count: number | null; setCount: (n: number | null) => void }>({
  count: null,
  setCount: () => {},
});
export const useHeaderCount = () => useContext(CountCtx);

const NAV = [
  { to: "/", icon: "▦", label: "Ad Library", adminOnly: false },
  { to: "/users", icon: "◉", label: "Users", adminOnly: true },
];

export default function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();
  const isMobile = useIsNarrow();
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 760);
  const [count, setCount] = useState<number | null>(null);
  const [selfOpen, setSelfOpen] = useState(false);
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    setOpen(!isMobile);
  }, [isMobile]);

  const go = (to: string) => {
    navigate(to);
    if (isMobile) setOpen(false);
  };

  return (
    <CountCtx.Provider value={{ count, setCount }}>
      <div style={{ display: "flex", minHeight: "100vh", overflowX: "hidden" }}>
        {isMobile && open && (
          <div
            onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, background: "rgba(16,24,22,.42)", zIndex: 79, animation: "fbspyFade .12s ease" }}
          />
        )}
        {/* SIDEBAR */}
        <aside
          style={{
            width: isMobile ? 268 : open ? 232 : 72,
            flex: "none",
            background: "linear-gradient(180deg,#1B2A2C,#152123)",
            display: "flex",
            flexDirection: "column",
            transition: isMobile ? "transform .22s ease" : "width .2s ease",
            position: isMobile ? "fixed" : "sticky",
            top: 0,
            left: 0,
            height: "100svh",
            zIndex: isMobile ? 80 : 1,
            transform: isMobile && !open ? "translateX(-100%)" : "translateX(0)",
            boxShadow: isMobile && open ? "18px 0 48px rgba(16,24,22,.24)" : "none",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "18px 16px 16px" }}>
            <div style={{ width: 38, height: 38, borderRadius: 12, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", display: "flex", alignItems: "center", justifyContent: "center", flex: "none", boxShadow: "0 4px 12px rgba(46,158,115,.4)" }}>
              <div style={{ width: 16, height: 16, borderRadius: 999, border: "2.5px solid #fff", position: "relative" }}>
                <div style={{ position: "absolute", width: 4, height: 4, borderRadius: 999, background: "#fff", top: 3.5, left: 3.5 }} />
              </div>
            </div>
            {open && (
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-.02em", color: "#fff", lineHeight: 1 }}>FB&nbsp;SPY</div>
                <div style={{ fontSize: 10, color: "#7FB8A6", letterSpacing: ".1em", textTransform: "uppercase", fontWeight: 600, marginTop: 3 }}>Ad Console</div>
              </div>
            )}
          </div>

          <nav style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
            {NAV.filter((n) => !n.adminOnly || isAdmin).map((n) => {
              const active = n.to === "/" ? loc.pathname === "/" || loc.pathname.startsWith("/ads") : loc.pathname === n.to;
              return (
                <button key={n.to} onClick={() => go(n.to)} title={n.label} style={navItemStyle(active)}>
                  <span style={{ fontSize: 17, width: 22, textAlign: "center", flex: "none" }}>{n.icon}</span>
                  {open && <span style={{ flex: 1, textAlign: "left" }}>{n.label}</span>}
                </button>
              );
            })}
          </nav>

          <div style={{ padding: 10, borderTop: "1px solid rgba(255,255,255,.08)" }}>
            <button onClick={() => setSelfOpen(true)} style={{ display: "flex", alignItems: "center", gap: 11, width: "100%", background: "transparent", border: "none", padding: 8, borderRadius: 11, cursor: "pointer" }}>
              <div style={{ width: 38, height: 38, borderRadius: 999, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 13.5, flex: "none" }}>
                {mono(user?.username || "?")}
              </div>
              {open && (
                <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "center", gap: 3 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#EAF2EE", lineHeight: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%", fontFamily: MONO }}>{user?.username}</div>
                  <div style={rolePill(user?.role === "admin")}>{user?.role}</div>
                </div>
              )}
            </button>
            {open && (
              <button onClick={logout} style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", marginTop: 4, background: "transparent", border: "none", padding: "8px 10px", borderRadius: 10, color: "#7FB8A6", fontSize: 12.5, fontWeight: 500, cursor: "pointer" }}>
                <span>⏻</span><span>Log out</span>
              </button>
            )}
          </div>
        </aside>

        {/* MAIN COLUMN */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <TopBar isMobile={isMobile} onToggleSidebar={() => setOpen((o) => !o)} />
          <div className="fbspy-scroll" style={{ flex: 1, overflow: "auto" }}>
            <Outlet />
          </div>
        </div>
      </div>

      {selfOpen && user && (
        <UserDrawer mode="self" user={user} currentUser={user} onClose={() => setSelfOpen(false)} />
      )}
    </CountCtx.Provider>
  );
}

function TopBar({ isMobile, onToggleSidebar }: { isMobile: boolean; onToggleSidebar: () => void }) {
  const { filters, set } = useUrlFilters();
  const navigate = useNavigate();
  const loc = useLocation();
  const { count } = useHeaderCount();
  const isLibrary = loc.pathname === "/";

  return (
    <header
      style={{
        minHeight: isMobile ? 58 : 64, flex: "none", background: "rgba(245,247,246,.9)", backdropFilter: "blur(10px)",
        borderBottom: `1px solid ${PAL.border}`, display: "flex", alignItems: "center", gap: isMobile ? 9 : 14, padding: isMobile ? "8px 12px" : "0 22px",
        position: "sticky", top: 0, zIndex: 30,
      }}
    >
      <button onClick={onToggleSidebar} title="Toggle sidebar" style={{ width: 36, height: 36, borderRadius: 10, border: `1px solid ${PAL.border}`, background: "#fff", color: PAL.text2, cursor: "pointer", flex: "none", fontSize: 15, display: "flex", alignItems: "center", justifyContent: "center" }}>☰</button>
      <div style={{ position: "relative", flex: 1, maxWidth: isMobile ? "none" : 520, minWidth: 0 }}>
        <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: PAL.muted, fontSize: 15, pointerEvents: "none" }}>⌕</span>
        <DebouncedInput
          value={filters.q || ""}
          onChange={(v) => { if (!isLibrary) navigate("/"); set("q", v || null); }}
          placeholder={isMobile ? "Search ads..." : "Search ad copy, headline, advertiser…  ( / )"}
          style={{ width: "100%", height: 40, border: `1px solid ${PAL.border}`, borderRadius: 11, padding: "0 14px 0 38px", fontSize: 13.5, color: PAL.text, background: "#fff", outline: "none", boxShadow: "0 1px 2px rgba(16,40,30,.03)" }}
        />
      </div>
      {!isMobile && <div style={{ flex: 1 }} />}
      {!isMobile && isLibrary && count != null && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: PAL.muted }}>
          <span style={{ fontWeight: 600, color: PAL.text, fontVariantNumeric: "tabular-nums" }}>{count.toLocaleString()}</span>
          <span>ads</span>
        </div>
      )}
    </header>
  );
}

function navItemStyle(active: boolean): CSSProperties {
  return active
    ? { display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "linear-gradient(135deg,rgba(63,191,154,.22),rgba(46,158,115,.16))", color: "#fff", fontSize: 13.5, fontWeight: 600, cursor: "pointer", boxShadow: "inset 0 0 0 1px rgba(127,184,166,.25)" }
    : { display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "10px 12px", borderRadius: 12, border: "none", background: "transparent", color: "#AFCFC3", fontSize: 13.5, fontWeight: 500, cursor: "pointer" };
}

function rolePill(admin: boolean): CSSProperties {
  return { display: "inline-block", fontSize: 9.5, fontWeight: 700, letterSpacing: ".05em", lineHeight: 1.3, textTransform: "uppercase", color: admin ? "#8FE3C8" : "#9FB0AB", background: "rgba(255,255,255,.08)", borderRadius: 999, padding: "2px 8px" };
}
