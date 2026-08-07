import { useState, type CSSProperties } from "react";
import type { AdStats, AdType } from "../api/types";
import { PAL, segStyle, cntStyle, selectStyle } from "../theme";
import { useUrlFilters } from "../useUrlFilters";
import { countryFlag, languageLabel } from "../lib/media";
import { useHorizontalSwipe } from "../lib/useHorizontalSwipe";
import DebouncedInput from "./DebouncedInput";

const facetMap = (arr?: { value: string; count: number }[]) =>
  Object.fromEntries((arr || []).map((f) => [f.value, f.count])) as Record<string, number>;

const H: CSSProperties = { fontSize: 11, fontWeight: 700, color: PAL.muted, letterSpacing: ".07em", textTransform: "uppercase", margin: "6px 0 9px" };

interface Opt { label: string; count?: number; active: boolean; onClick: () => void; }

function Seg({ opts, wrap = true }: { opts: Opt[]; wrap?: boolean }) {
  return (
    <div style={{ display: "flex", flexWrap: wrap ? "wrap" : "nowrap", gap: 6, marginBottom: 18 }}>
      {opts.map((o, i) => (
        <button key={i} onClick={o.onClick} style={segStyle(o.active)}>
          <span>{o.label}</span>
          {o.count != null && <span style={cntStyle(o.active)}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export default function FilterRail({ open, stats, mobile = false, onClose }: { open: boolean; stats?: AdStats; mobile?: boolean; onClose?: () => void }) {
  const { filters: f, set, setBool, toggleAdType, clearAll, pills } = useUrlFilters();
  const [advanced, setAdvanced] = useState(false);
  const closeSwipe = useHorizontalSwipe({
    enabled: mobile && open,
    onSwipeLeft: onClose,
  });

  const total = stats?.total_ads;
  const byType = facetMap(stats?.by_type);
  const byFormat = facetMap(stats?.by_format);
  const byCountry = stats?.by_country || [];
  const byLanguage = stats?.by_language || [];
  const byVertical = stats?.by_vertical || [];
  const byPlacement = stats?.by_placement || [];
  const byAdv = stats?.by_advertiser || [];
  const byDom = stats?.by_domain || [];

  const inputStyle: CSSProperties = { width: "100%", height: 38, border: `1px solid ${PAL.border}`, borderRadius: 10, padding: "0 12px", fontSize: 13, background: "#fff", outline: "none", marginBottom: 16, fontFamily: "'JetBrains Mono',monospace" };

  return (
    <div
      aria-hidden={!open}
      data-testid="filter-rail"
      {...closeSwipe}
      style={{
        width: mobile ? 304 : open ? 284 : 0,
        maxWidth: mobile ? "88vw" : undefined,
        flex: "none",
        height: mobile ? "100svh" : "100%",
        overflow: "hidden",
        background: PAL.panel,
        borderRight: open ? `1px solid ${PAL.border}` : "none",
        transition: mobile ? "transform .22s ease" : "width .22s ease, border-color .22s ease",
        position: mobile ? "fixed" : "relative",
        top: mobile ? 0 : undefined,
        left: mobile ? 0 : undefined,
        bottom: mobile ? 0 : undefined,
        zIndex: mobile ? 72 : undefined,
        transform: mobile && !open ? "translateX(-100%)" : "translateX(0)",
        boxShadow: mobile && open ? "18px 0 48px rgba(16,24,22,.22)" : "none",
      }}
    >
      <div
        className="fbspy-scroll"
        style={{ width: mobile ? "100%" : 284, height: "100%", padding: mobile ? "18px 14px 40px" : "18px 16px 40px", overflowY: "auto", overflowX: "hidden", opacity: open ? 1 : 0, transform: open ? "translateX(0)" : "translateX(-18px)", transition: "opacity .16s ease, transform .22s ease", pointerEvents: open ? "auto" : "none" }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: PAL.head, letterSpacing: "-.01em", display: "flex", alignItems: "center", gap: 7 }}>
            Filters
            {pills.length > 0 && (
              <span style={{ background: PAL.emerald, color: "#fff", fontSize: 10, fontWeight: 700, borderRadius: 999, minWidth: 17, height: 17, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "0 5px" }}>{pills.length}</span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <button onClick={clearAll} style={{ background: "none", border: "none", color: PAL.emerald, fontSize: 12, fontWeight: 600, cursor: "pointer", padding: 4 }}>Clear all</button>
            {mobile && <button onClick={onClose} title="Close filters" style={{ width: 30, height: 30, borderRadius: 9, border: `1px solid ${PAL.border}`, background: "#fff", color: PAL.text2, cursor: "pointer", fontSize: 18, lineHeight: 1 }}>×</button>}
          </div>
        </div>

        <div style={H}>Ad type</div>
        <Seg opts={(["link", "in_facebook", "video"] as AdType[]).map((t) => ({
          label: t === "in_facebook" ? "In\u2011Facebook" : t === "link" ? "Link" : "Video",
          count: byType[t], active: (f.ad_type || []).includes(t), onClick: () => toggleAdType(t),
        }))} />

        <div style={H}>Format</div>
        <Seg opts={[
          { label: "All", count: total, active: !f.format, onClick: () => set("format", null) },
          { label: "Image", count: byFormat["image"], active: f.format === "image", onClick: () => set("format", "image") },
          { label: "Video", count: byFormat["video"], active: f.format === "video", onClick: () => set("format", "video") },
        ]} />

        <div style={audienceSection}>
          <div style={{ ...H, margin: "0 0 10px" }}>Audience</div>
          <label htmlFor="filter-geo" style={facetLabel}>Geo</label>
          <select
            id="filter-geo"
            aria-label="Filter ads by geo"
            value={f.country || ""}
            onChange={(e) => set("country", e.target.value || null)}
            style={audienceSelect}
          >
            <option value="">🌐  All geos</option>
            {byCountry.map((c) => (
              <option key={c.value} value={c.value}>
                {countryFlag(c.value)}  {c.value || "Unknown"} · {c.count}
              </option>
            ))}
          </select>

          <label htmlFor="filter-language" style={facetLabel}>Ad language</label>
          <select
            id="filter-language"
            aria-label="Filter ads by language"
            value={f.language || ""}
            onChange={(e) => set("language", e.target.value || null)}
            style={{ ...audienceSelect, marginBottom: 0 }}
          >
            <option value="">Aa  All languages</option>
            {byLanguage.map((item) => (
              <option key={item.value} value={item.value}>
                {item.value.toUpperCase()}  {languageLabel(item.value)} · {item.count}
              </option>
            ))}
          </select>
        </div>

        <div style={H}>Has landing</div>
        <Seg opts={[
          { label: "All", count: total, active: f.has_landing == null, onClick: () => setBool("has_landing", null) },
          { label: "Resolved", count: stats?.resolved_ads, active: f.has_landing === true, onClick: () => setBool("has_landing", true) },
          { label: "No landing", count: total != null && stats ? total - stats.resolved_ads : undefined, active: f.has_landing === false, onClick: () => setBool("has_landing", false) },
        ]} />

        <div style={H}>Screenshot quality</div>
        <Seg opts={[
          { label: "All", count: total, active: f.screenshot_ok == null, onClick: () => setBool("screenshot_ok", null) },
          { label: "OK", count: total != null && stats ? total - stats.bad_screenshots : undefined, active: f.screenshot_ok === true, onClick: () => setBool("screenshot_ok", true) },
          { label: "Problem", count: stats?.bad_screenshots, active: f.screenshot_ok === false, onClick: () => setBool("screenshot_ok", false) },
        ]} />

        <div style={H}>Advertiser</div>
        <DebouncedInput value={f.advertiser__search || ""} onChange={(v) => set("advertiser__search", v || null)} placeholder="contains…" list="advlist" style={inputStyle} />
        <datalist id="advlist">{byAdv.slice(0, 30).map((a) => <option key={a.value} value={a.value} />)}</datalist>

        <div style={H}>Domain</div>
        <DebouncedInput value={f.displayed_domain__search || ""} onChange={(v) => set("displayed_domain__search", v || null)} placeholder="contains…" list="domlist" style={inputStyle} />
        <datalist id="domlist">{byDom.slice(0, 30).map((d) => <option key={d.value} value={d.value} />)}</datalist>

        <button onClick={() => setAdvanced((a) => !a)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", cursor: "pointer", padding: "8px 0", borderTop: `1px solid ${PAL.border}`, color: PAL.text2, fontSize: 11, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase" }}>
          <span>Advanced</span>
          <span style={{ transition: "transform .2s ease", transform: advanced ? "rotate(180deg)" : "none", display: "inline-block" }}>⌄</span>
        </button>

        {advanced && (
          <div style={{ paddingTop: 6 }}>
            <div style={H}>Cloaking</div>
            <Seg opts={[
              { label: "Any", active: f.cloaking == null, onClick: () => setBool("cloaking", null) },
              { label: "Suspected", active: f.cloaking === true, onClick: () => setBool("cloaking", true) },
              { label: "Clean", active: f.cloaking === false, onClick: () => setBool("cloaking", false) },
            ]} />

            <div style={{ ...H, margin: "6px 0 7px" }}>Vertical</div>
            <select value={f.vertical || ""} onChange={(e) => set("vertical", e.target.value || null)} style={selectStyle}>
              <option value="">All verticals</option>
              {byVertical.map((v) => <option key={v.value} value={v.value}>{v.value || "Unknown"} ({v.count})</option>)}
            </select>

            <div style={{ ...H, margin: "6px 0 7px" }}>Placement</div>
            <select value={f.placement || ""} onChange={(e) => set("placement", e.target.value || null)} style={selectStyle}>
              <option value="">All placements</option>
              {byPlacement.map((p) => <option key={p.value} value={p.value}>{p.value} ({p.count})</option>)}
            </select>

            <div style={{ ...H, margin: "6px 0 7px" }}>FB Ad ID</div>
            <DebouncedInput value={f.fb_ad_id || ""} onChange={(v) => set("fb_ad_id", v || null)} placeholder="exact match…" style={{ ...inputStyle, marginBottom: 0 }} />
          </div>
        )}
      </div>
    </div>
  );
}

const audienceSection: CSSProperties = {
  borderTop: `1px solid ${PAL.border}`,
  borderBottom: `1px solid ${PAL.border}`,
  padding: "14px 0 16px",
  margin: "0 0 18px",
};

const facetLabel: CSSProperties = {
  display: "block",
  margin: "0 0 6px",
  color: PAL.text2,
  fontSize: 12,
  fontWeight: 650,
};

const audienceSelect: CSSProperties = {
  ...selectStyle,
  height: 42,
  marginBottom: 12,
  borderRadius: 8,
  fontWeight: 600,
  boxShadow: "0 1px 2px rgba(16,40,30,.03)",
};
