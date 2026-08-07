import type { CSSProperties } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAd } from "../api/hooks";
import { PAL } from "../theme";
import { useCopy } from "../toasts";
import AdDetail from "../components/AdDetail";
import { landingUrl } from "../lib/media";
import { useIsNarrow } from "../lib/responsive";

export default function AdDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const copy = useCopy();
  const ad = useAd(id);
  const isMobile = useIsNarrow();

  return (
    <div style={{ padding: isMobile ? "12px 12px 42px" : "18px 30px 60px", maxWidth: 1280 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <button onClick={() => navigate("/")} style={{ display: "inline-flex", alignItems: "center", gap: 7, background: "none", border: "none", color: PAL.text2, fontSize: 13, fontWeight: 600, cursor: "pointer", padding: "6px 0" }}>‹ Back to library</button>
        <div style={{ flex: 1 }} />
        {ad.data && (
          <>
            <button onClick={() => copy(landingUrl(ad.data!))} style={hdrBtn}>⧉ Copy landing</button>
            {(ad.data.landing_full || ad.data.landing_clean) && (
              <button onClick={() => window.open(ad.data!.landing_full || `https://${(ad.data!.landing_clean || "").replace(/^https?:\/\//, "")}`, "_blank", "noopener")} style={hdrBtn}>↗ Open landing</button>
            )}
          </>
        )}
      </div>

      {ad.isLoading ? (
        <div style={{ padding: 80, textAlign: "center", color: PAL.muted }}>
          <span style={{ width: 26, height: 26, border: "3px solid #E3E7E5", borderTopColor: PAL.emerald, borderRadius: 999, display: "inline-block", animation: "fbspySpin .8s linear infinite" }} />
        </div>
      ) : ad.isError || !ad.data ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 20px", textAlign: "center" }}>
          <div style={{ fontSize: 64, fontWeight: 800, color: PAL.muted, letterSpacing: "-.04em" }}>404</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: PAL.head, margin: "8px 0 6px" }}>Ad not found</div>
          <div style={{ fontSize: 13.5, color: PAL.text2, maxWidth: 340, marginBottom: 20 }}>That ad doesn’t exist or may have been removed.</div>
          <button onClick={() => navigate("/")} style={primary}>Back to Ad Library</button>
        </div>
      ) : (
        <AdDetail ad={ad.data} />
      )}
    </div>
  );
}

const hdrBtn: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, background: "#fff", color: PAL.text, border: `1px solid ${PAL.border}`, borderRadius: 10, padding: "8px 13px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" };
const primary: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 7, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", color: "#fff", border: "none", borderRadius: 11, padding: "10px 18px", fontSize: 13.5, fontWeight: 600, cursor: "pointer", boxShadow: "0 4px 14px rgba(46,158,115,.32)" };
