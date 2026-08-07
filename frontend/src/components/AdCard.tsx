import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import type { Ad } from "../api/types";
import { PAL, TYPEMETA, cardShadow } from "../theme";
import { advColor, buildMedia, countryFlag, countryLabel, hasLanding, landingUrl, mono, primaryMedia, rel } from "../lib/media";
import { useCopy } from "../toasts";
import SafeImage from "./SafeImage";

export default function AdCard({ ad, onOpen }: { ad: Ad; onOpen?: (ad: Ad) => void }) {
  const navigate = useNavigate();
  const copy = useCopy();
  const tm = TYPEMETA[ad.ad_type];
  const media = buildMedia(ad);
  const primary = primaryMedia(ad);
  const isVideo = ad.has_video || ad.format === "video";
  const badShot = ad.screenshot_ok === false;
  const landing = hasLanding(ad);
  const geo = countryLabel(ad.country);
  const flag = countryFlag(ad.country);

  const open = () => (onOpen ? onOpen(ad) : navigate(`/ads/${ad.id}`));

  return (
    <div className="fbspy-card" onClick={open} style={{ background: "#fff", border: `1px solid ${PAL.border}`, borderRadius: 16, overflow: "hidden", cursor: "pointer", boxShadow: cardShadow, position: "relative", display: "flex", flexDirection: "column" }}>
      {/* media */}
      <div style={{ position: "relative", aspectRatio: "4 / 5", background: "#EEF2F0", overflow: "hidden" }}>
        <SafeImage
          src={primary.poster || primary.url}
          fit="cover"
          position="center top"
          fallbackLabel={badShot ? (ad.screenshot_issue || "bad screenshot").replace(/_/g, " ") : "no screenshot"}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        />
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 46, background: "linear-gradient(transparent,#fff)" }} />

        {isVideo && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(24,38,40,.18)" }}>
            <div style={{ width: 52, height: 52, borderRadius: 999, background: "rgba(255,255,255,.92)", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 4px 14px rgba(0,0,0,.25)" }}>
              <span style={{ color: "#182628", fontSize: 20, marginLeft: 3 }}>▶</span>
            </div>
          </div>
        )}

        <div style={{ position: "absolute", top: 9, left: 9, display: "flex", gap: 6 }}>
          <span style={typeChip(tm)}>{tm.i} {tm.l}</span>
          <span title={`Geo: ${geo}`} style={geoChip}>{flag}</span>
        </div>
        <div style={{ position: "absolute", top: 9, right: 9, display: "flex", gap: 6 }}>
          {isVideo && ad.format === "video" && (
            <span style={{ background: "rgba(24,38,40,.78)", color: "#fff", fontSize: 10.5, fontWeight: 700, borderRadius: 999, padding: "3px 8px", backdropFilter: "blur(4px)" }}>▶ video</span>
          )}
          {media.length > 1 && (
            <span style={{ background: "rgba(255,255,255,.92)", color: PAL.text, fontSize: 10.5, fontWeight: 700, borderRadius: 999, padding: "3px 8px", boxShadow: "0 1px 3px rgba(0,0,0,.15)" }}>❏ {media.length}</span>
          )}
          {badShot && (
            <span style={{ background: "#FBE2DF", color: "#B23B31", fontSize: 10.5, fontWeight: 700, borderRadius: 999, padding: "3px 8px" }}>⚠</span>
          )}
        </div>

        <div className="fbspy-quick" style={{ position: "absolute", bottom: 9, right: 9, display: "flex", gap: 6, opacity: 0, transform: "translateY(4px)", transition: "all .16s ease" }}>
          <button
            title="Copy landing URL"
            onClick={(e) => { e.stopPropagation(); copy(landingUrl(ad)); }}
            style={quickBtn}
          >⧉</button>
          <button
            title="Open landing"
            onClick={(e) => { e.stopPropagation(); const u = ad.landing_full || ad.landing_clean; if (u) window.open(u, "_blank", "noopener"); }}
            style={quickBtn}
          >↗</button>
        </div>
      </div>

      {/* body */}
      <div style={{ padding: "12px 13px 13px", flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <div style={monoStyle(advColor(ad.advertiser))}>{mono(ad.advertiser)}</div>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: PAL.head, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{ad.advertiser}</div>
          <span style={ctaPill}>{ad.cta}</span>
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, color: PAL.text, lineHeight: 1.35, marginBottom: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ad.headline}</div>
        <div style={{ fontSize: 12, color: PAL.text2, lineHeight: 1.45, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", marginBottom: 11, flex: 1 }}>{ad.ad_text}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 7, paddingTop: 10, borderTop: `1px solid ${PAL.panel}` }}>
          <span style={{ fontSize: 11, color: PAL.muted, flex: "none" }}>🔗</span>
          <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: PAL.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{ad.displayed_domain}</span>
          {landing && <span title="Has landing page" style={{ width: 7, height: 7, borderRadius: 999, background: PAL.emerald, flex: "none" }} />}
          <span style={{ fontSize: 11, color: PAL.muted, flex: "none", fontVariantNumeric: "tabular-nums" }}>{rel(ad.captured_at)}</span>
        </div>
      </div>
    </div>
  );
}

const quickBtn: CSSProperties = { width: 32, height: 32, borderRadius: 9, border: "none", background: "rgba(255,255,255,.95)", color: "#28312E", cursor: "pointer", fontSize: 13, boxShadow: "0 2px 6px rgba(0,0,0,.15)" };
const ctaPill: CSSProperties = { fontSize: 10.5, fontWeight: 700, color: PAL.head, background: "#F0F2EF", border: `1px solid ${PAL.border}`, borderRadius: 999, padding: "3px 9px", whiteSpace: "nowrap", flex: "none" };
const typeChip = (tm: { fg: string; bg: string }): CSSProperties => ({ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700, color: tm.fg, background: tm.bg, borderRadius: 999, padding: "3px 9px", boxShadow: "0 1px 2px rgba(0,0,0,.06)" });
const geoChip: CSSProperties = { width: 24, height: 24, borderRadius: 999, border: "1px solid rgba(255,255,255,.82)", background: "rgba(255,255,255,.94)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 15, boxShadow: "0 1px 3px rgba(0,0,0,.12)", flex: "none" };
const monoStyle = (c: string): CSSProperties => ({ width: 24, height: 24, borderRadius: 999, background: c, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, flex: "none" });
