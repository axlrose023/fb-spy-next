import type { CSSProperties } from "react";

/* ── Palette — copied verbatim from the approved mockup ─────────────────────── */
export const PAL = {
  mint: "#3FBF9A",
  emerald: "#2E9E73",
  softmint: "#E4F6F0",
  canvas: "#F5F7F6",
  card: "#FFFFFF",
  panel: "#F1F4F2",
  border: "#E3E7E5",
  text: "#28312E",
  text2: "#5C6661",
  muted: "#8A938E",
  head: "#202825",
  dark: "#182628",
  warn: "#E8A93C",
  danger: "#E2574C",
  slate: "#5B7A86",
} as const;

export const FONT = "'Inter',system-ui,sans-serif";
export const MONO = "'JetBrains Mono',monospace";

/* Deterministic advertiser monogram colours (mockup used a fixed palette). */
export const COLORS = [
  "#2E9E73", "#5B7A86", "#E2574C", "#E8A93C", "#3FBF9A",
  "#7A5BB0", "#C2557A", "#3B7FB0", "#4F8A4F", "#B07A3B",
];

export const TYPEMETA: Record<string, { l: string; i: string; bg: string; fg: string }> = {
  link: { l: "Link", i: "↗", bg: "#E4F6F0", fg: "#2E9E73" },
  in_facebook: { l: "In\u2011Facebook", i: "⌂", bg: "#ECEFED", fg: "#5C6661" },
  video: { l: "Video", i: "▶", bg: "#E7EEF1", fg: "#5B7A86" },
};

export const KINDMETA: Record<string, { l: string; c: string; bg: string }> = {
  screenshot: { l: "Screenshot", c: "#2E9E73", bg: "#E4F6F0" },
  landing: { l: "Full landing page", c: "#5B7A86", bg: "#E7EEF1" },
  creative: { l: "Original creative", c: "#9A7B2E", bg: "#FAEFD6" },
  video: { l: "Video", c: "#7A5BB0", bg: "#F3EAF6" },
};

/* ── Reusable inline-style helpers (ported from the mockup's logic class) ───── */
export const segStyle = (active: boolean): CSSProperties =>
  active
    ? { padding: "7px 11px", borderRadius: 999, border: `1px solid ${PAL.mint}`, background: PAL.softmint, color: PAL.emerald, fontSize: 12.5, fontWeight: 600, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6, transition: "all .15s ease", whiteSpace: "nowrap" }
    : { padding: "7px 11px", borderRadius: 999, border: `1px solid ${PAL.border}`, background: "#fff", color: PAL.text2, fontSize: 12.5, fontWeight: 500, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6, transition: "all .15s ease", whiteSpace: "nowrap" };

export const cntStyle = (active: boolean): CSSProperties => ({
  fontSize: 10.5, fontWeight: 700, color: active ? "#1E6B4F" : PAL.muted,
  background: active ? "#CDEFE4" : PAL.panel, borderRadius: 999, padding: "1px 6px", fontVariantNumeric: "tabular-nums",
});

export const chip = (fg: string, bg: string): CSSProperties => ({
  display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
  color: fg, background: bg, borderRadius: 999, padding: "3px 10px",
});

export const primaryBtn: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 7, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)",
  color: "#fff", border: "none", borderRadius: 11, padding: "10px 18px", fontSize: 13.5, fontWeight: 600,
  cursor: "pointer", boxShadow: "0 4px 14px rgba(46,158,115,.32)",
};
export const secondaryBtn: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 7, background: "#fff", color: PAL.text,
  border: `1px solid ${PAL.border}`, borderRadius: 11, padding: "10px 18px", fontSize: 13.5, fontWeight: 600, cursor: "pointer",
};
export const navArrow: CSSProperties = {
  width: 34, height: 34, borderRadius: 10, border: `1px solid ${PAL.border}`, background: "#fff",
  color: PAL.text2, cursor: "pointer", fontSize: 15, display: "inline-flex", alignItems: "center", justifyContent: "center",
};
export const iconBtn: CSSProperties = {
  width: 30, height: 30, borderRadius: 9, border: `1px solid ${PAL.border}`, background: "#fff",
  color: PAL.text2, cursor: "pointer", fontSize: 13, flex: "none", display: "inline-flex", alignItems: "center", justifyContent: "center",
};
export const cardShadow = "0 1px 2px rgba(16,40,30,.04),0 6px 20px rgba(16,40,30,.05)";

export const selectStyle: CSSProperties = {
  width: "100%", height: 38, border: `1px solid ${PAL.border}`, borderRadius: 10, background: "#fff",
  padding: "0 30px 0 12px", fontSize: 13, color: PAL.text, outline: "none", cursor: "pointer", marginBottom: 16,
  appearance: "none",
  backgroundImage:
    "url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22><path d=%22M3 4.5L6 7.5L9 4.5%22 stroke=%22%235C6661%22 stroke-width=%221.5%22 fill=%22none%22 stroke-linecap=%22round%22/></svg>')",
  backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center",
};
