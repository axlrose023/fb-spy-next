import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { Ad } from "../api/types";
import { PAL, TYPEMETA, cardShadow, navArrow } from "../theme";
import { advColor, buildMedia, countryFlag, countryLabel, hasLanding, landingUrl, mono, primaryMedia, rel } from "../lib/media";
import { useAds, useStats } from "../api/hooks";
import { useUrlFilters } from "../useUrlFilters";
import { useCopy } from "../toasts";
import { useIsNarrow } from "../lib/responsive";
import { useHorizontalSwipe } from "../lib/useHorizontalSwipe";
import { useHeaderCount } from "../components/Shell";
import FilterRail from "../components/FilterRail";
import AdCard from "../components/AdCard";
import AdDetail from "../components/AdDetail";
import SafeImage from "../components/SafeImage";

export default function Library() {
  const navigate = useNavigate();
  const { filters, view, set, setView, pills, clearAll } = useUrlFilters();
  const ads = useAds(filters);
  const stats = useStats();
  const { setCount } = useHeaderCount();
  const copy = useCopy();
  const isMobile = useIsNarrow();
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [railOpen, setRailOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 760);
  const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const items = ads.data?.items || [];
  const total = ads.data?.total ?? 0;

  useEffect(() => { if (ads.data) setCount(ads.data.total); return () => setCount(null); }, [ads.data, setCount]);
  useEffect(() => { setRailOpen(!isMobile); }, [isMobile]);

  const gridContainer: CSSProperties = {
    display: "grid",
    gridTemplateColumns: isMobile ? "minmax(0,1fr)" : density === "compact" ? "repeat(auto-fill,minmax(210px,1fr))" : "repeat(auto-fill,minmax(248px,1fr))",
    gap: isMobile ? 12 : density === "compact" ? 12 : 16,
  };

  const selectedIndex = items.findIndex((a) => a.id === selectedId);
  const selectedAd = selectedIndex >= 0 ? items[selectedIndex] : null;
  const stepAd = (dir: number) => {
    if (selectedIndex < 0) return;
    const n = (selectedIndex + dir + items.length) % items.length;
    setSelectedId(items[n].id);
  };
  const detailSwipe = useHorizontalSwipe({
    enabled: isMobile && selectedIndex >= 0 && items.length > 1,
    onSwipeLeft: () => stepAd(1),
    onSwipeRight: () => stepAd(-1),
    ignoreSelector: "[data-horizontal-swipe]",
  });
  const changePage = (page: number) => {
    if (page === filters.page) return;
    set("page", String(page), false);
    requestAnimationFrame(() => {
      contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
  };

  return (
    <div style={{ display: "flex", alignItems: "stretch", height: isMobile ? "calc(100svh - 58px)" : "calc(100vh - 64px)", overflow: "hidden" }}>
      {isMobile && railOpen && (
        <div onClick={() => setRailOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(16,24,22,.38)", zIndex: 71, animation: "fbspyFade .12s ease" }} />
      )}
      <FilterRail open={railOpen} stats={stats.data} mobile={isMobile} onClose={() => setRailOpen(false)} />

      <div ref={contentRef} data-testid="library-scroll" className="fbspy-scroll" style={{ flex: 1, minWidth: 0, padding: isMobile ? "12px 12px 44px" : "18px 22px 60px", height: "100%", overflowY: "auto", overflowX: "hidden" }}>
        {/* results header */}
        <div style={{ display: "flex", alignItems: isMobile ? "stretch" : "center", gap: isMobile ? 10 : 12, flexWrap: "wrap", marginBottom: 14 }}>
          <button onClick={() => setRailOpen((o) => !o)} title={railOpen ? "Hide filters" : "Show filters"} style={filterToggle(railOpen)}>
            <span style={{ fontSize: 14, lineHeight: 1 }}>{railOpen ? "‹" : "›"}</span>
            <span>Filters</span>
            {pills.length > 0 && <span style={filterCount}>{pills.length}</span>}
          </button>
          <div style={{ fontSize: 20, fontWeight: 800, color: PAL.head, letterSpacing: "-.02em", fontVariantNumeric: "tabular-nums" }}>
            {total.toLocaleString()}<span style={{ fontSize: 14, fontWeight: 600, color: PAL.muted, marginLeft: 6 }}>ads</span>
          </div>
          <div style={{ flex: isMobile ? "1 1 100%" : 1 }} />
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", width: isMobile ? "100%" : "auto" }}>
            <span style={{ fontSize: 12, color: PAL.muted }}>Sort</span>
            <select value={filters.order_by} onChange={(e) => set("order_by", e.target.value, false)} style={{ ...sortSelect, flex: isMobile ? "1 1 160px" : "none", minWidth: 0 }}>
              <option value="-captured_at">Newest captured</option>
              <option value="captured_at">Oldest captured</option>
              <option value="advertiser">Advertiser A–Z</option>
              <option value="displayed_domain">Domain A–Z</option>
            </select>
            {view === "grid" && (
              <ControlGroup label="Density" compact={isMobile}>
                <Toggle>
                  <Tbtn active={density === "comfortable"} onClick={() => setDensity("comfortable")} title="Roomy card density">▤ <span>Roomy</span></Tbtn>
                  <Tbtn active={density === "compact"} onClick={() => setDensity("compact")} title="Compact card density">≡ <span>Compact</span></Tbtn>
                </Toggle>
              </ControlGroup>
            )}
            <ControlGroup label="View" compact={isMobile}>
              <Toggle>
                <Tbtn active={view === "grid"} onClick={() => setView("grid")} title="Card grid view">▦ <span>Cards</span></Tbtn>
                <Tbtn active={view === "list"} onClick={() => setView("list")} title="Row list view">≣ <span>Rows</span></Tbtn>
              </Toggle>
            </ControlGroup>
          </div>
        </div>

        {/* active pills */}
        {pills.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16, alignItems: "center" }}>
            {pills.map((p) => (
              <button key={p.key} onClick={p.onRemove} style={{ display: "inline-flex", alignItems: "center", gap: 7, background: PAL.softmint, border: "1px solid #9FDBC8", color: PAL.emerald, borderRadius: 999, padding: "5px 9px 5px 11px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                <span style={{ color: PAL.text2, fontWeight: 500 }}>{p.group}</span><span>{p.label}</span>
                <span style={{ width: 15, height: 15, borderRadius: 999, background: "#9FDBC8", color: "#1E6B4F", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11 }}>×</span>
              </button>
            ))}
            <button onClick={clearAll} style={{ background: "none", border: "none", color: PAL.muted, fontSize: 12, fontWeight: 600, cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 2 }}>Clear all</button>
          </div>
        )}

        {/* states */}
        {ads.isLoading ? (
          <div style={gridContainer}>
            {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        ) : ads.isError ? (
          <Centered icon="⚠" iconBg="#FBE2DF" title="Couldn’t load ads" sub="The server didn’t respond. Check your connection and try again.">
            <button onClick={() => ads.refetch()} style={primary}>↻ Retry</button>
          </Centered>
        ) : items.length === 0 ? (
          <Centered icon="⌕" iconBg="#ECEFED" title="No ads match these filters" sub="Try removing a filter or broadening your search.">
            <button onClick={clearAll} style={secondary}>Clear all filters</button>
          </Centered>
        ) : view === "grid" ? (
          <>
            <div style={gridContainer}>
              {items.map((ad) => <AdCard key={ad.id} ad={ad} onOpen={(a) => setSelectedId(a.id)} />)}
            </div>
            <Pager compact={isMobile} page={ads.data!.page} totalPages={ads.data!.total_pages} hasPrev={ads.data!.has_prev} hasNext={ads.data!.has_next} total={total} count={items.length} pageSize={ads.data!.page_size} onPage={changePage} />
          </>
        ) : (
          <>
            <ListView items={items} onOpen={(a) => setSelectedId(a.id)} />
            <Pager compact={isMobile} page={ads.data!.page} totalPages={ads.data!.total_pages} hasPrev={ads.data!.has_prev} hasNext={ads.data!.has_next} total={total} count={items.length} pageSize={ads.data!.page_size} onPage={changePage} />
          </>
        )}
      </div>

      {/* DETAIL DRAWER */}
      {selectedAd && (
        <>
          <div onClick={() => setSelectedId(null)} style={{ position: "fixed", inset: 0, background: "rgba(24,38,40,.32)", zIndex: 50, animation: "fbspyFade .15s ease" }} />
          <div data-testid="ad-detail-drawer" className="fbspy-scroll" {...detailSwipe} style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: isMobile ? "100vw" : 760, maxWidth: "100vw", background: "#fff", zIndex: 51, boxShadow: "-20px 0 60px rgba(16,40,30,.18)", overflow: "auto", animation: "fbspyDrawer .2s ease" }}>
            <DrawerHeader
              onPrev={() => stepAd(-1)} onNext={() => stepAd(1)}
              onCopyLanding={() => copy(landingUrl(selectedAd))}
              onOpenPage={() => { const id = selectedAd.id; setSelectedId(null); navigate(`/ads/${id}`); }}
              onClose={() => setSelectedId(null)}
            />
            <div style={{ padding: isMobile ? "14px 12px 34px" : "20px 22px 40px" }}>
              <AdDetail ad={selectedAd} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ── drawer header ─────────────────────────────────────────────────────────── */
function DrawerHeader({ onPrev, onNext, onCopyLanding, onOpenPage, onClose }: { onPrev: () => void; onNext: () => void; onCopyLanding: () => void; onOpenPage: () => void; onClose: () => void }) {
  return (
    <div style={{ position: "sticky", top: 0, zIndex: 5, background: "rgba(255,255,255,.92)", backdropFilter: "blur(8px)", borderBottom: `1px solid ${PAL.border}`, display: "flex", alignItems: "center", gap: 8, padding: "13px 18px" }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: PAL.head, flex: 1 }}>Ad detail</div>
      <button onClick={onPrev} title="Previous (←)" style={navArrow}>‹</button>
      <button onClick={onNext} title="Next (→)" style={navArrow}>›</button>
      <button onClick={onCopyLanding} title="Copy landing URL" style={navArrow}>⧉</button>
      <button onClick={onOpenPage} title="Open full page" style={navArrow}>⤢</button>
      <button onClick={onClose} title="Close (Esc)" style={navArrow}>×</button>
    </div>
  );
}

/* ── list view ─────────────────────────────────────────────────────────────── */
const GRID_COLS = "60px minmax(170px,2fr) 58px 108px minmax(150px,1.8fr) 120px 96px 92px";
function ListView({ items, onOpen }: { items: Ad[]; onOpen: (a: Ad) => void }) {
  return (
    <div style={{ background: "#fff", border: `1px solid ${PAL.border}`, borderRadius: 16, overflow: "hidden", boxShadow: cardShadow }}>
      <div className="fbspy-scroll" style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 960 }}>
          <div style={{ display: "grid", gridTemplateColumns: GRID_COLS, gap: 16, padding: "12px 20px", background: "#F7FAF9", borderBottom: `1px solid ${PAL.border}`, fontSize: 11, fontWeight: 700, color: PAL.muted, letterSpacing: ".05em", textTransform: "uppercase" }}>
            <div>Media</div><div>Advertiser</div><div>Geo</div><div>Type</div><div>Domain</div><div>CTA</div><div>Captured</div><div>Status</div>
          </div>
          {items.map((ad) => {
            const tm = TYPEMETA[ad.ad_type];
            const isVideo = ad.has_video || ad.format === "video";
            const primary = primaryMedia(ad);
            const geo = countryLabel(ad.country);
            const flag = countryFlag(ad.country);
            const status = ad.screenshot_ok === false ? "Problem" : hasLanding(ad) ? "Resolved" : "—";
            const statusStyle: CSSProperties = ad.screenshot_ok === false
              ? { fontSize: 11, fontWeight: 600, color: "#B23B31", background: "#FBE2DF", borderRadius: 999, padding: "3px 9px" }
              : hasLanding(ad) ? { fontSize: 11, fontWeight: 600, color: PAL.emerald, background: PAL.softmint, borderRadius: 999, padding: "3px 9px" }
              : { fontSize: 11, fontWeight: 600, color: PAL.muted, background: PAL.panel, borderRadius: 999, padding: "3px 9px" };
            return (
              <div key={ad.id} className="fbspy-row" onClick={() => onOpen(ad)} style={{ display: "grid", gridTemplateColumns: GRID_COLS, gap: 16, padding: "12px 20px", borderBottom: "1px solid #F1F4F2", cursor: "pointer", alignItems: "center", transition: "background .12s ease" }}>
                <div style={{ width: 44, height: 44, borderRadius: 10, overflow: "hidden", position: "relative", flex: "none", background: advColor(ad.advertiser) }}>
                  <SafeImage src={primary.poster || primary.url} fit="cover" fallbackLabel="" style={{ width: "100%", height: "100%" }} />
                  {isVideo && <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 13, textShadow: "0 1px 3px rgba(0,0,0,.5)" }}>▶</span>}
                </div>
                <div style={{ minWidth: 0, display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 26, height: 26, borderRadius: 999, background: advColor(ad.advertiser), color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, flex: "none" }}>{mono(ad.advertiser)}</div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: PAL.head, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ad.advertiser}</div>
                    <div style={{ fontSize: 11.5, color: PAL.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ad.headline}</div>
                  </div>
                </div>
                <div style={{ minWidth: 0 }}><span title={`Geo: ${geo}`} style={rowGeoChip}>{flag}</span></div>
                <div style={{ minWidth: 0 }}><span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 600, color: tm.fg, background: tm.bg, borderRadius: 999, padding: "3px 9px" }}>{tm.l}</span></div>
                <div style={{ minWidth: 0 }}><span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: PAL.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>{ad.displayed_domain}</span></div>
                <div style={{ minWidth: 0 }}><span style={{ fontSize: 10.5, fontWeight: 700, color: PAL.head, background: "#F0F2EF", border: `1px solid ${PAL.border}`, borderRadius: 999, padding: "3px 9px", whiteSpace: "nowrap" }}>{ad.cta}</span></div>
                <div style={{ fontSize: 12, color: PAL.text2, fontVariantNumeric: "tabular-nums" }}>{rel(ad.captured_at)}</div>
                <div><span style={statusStyle}>{status}</span></div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const rowGeoChip: CSSProperties = { width: 28, height: 28, borderRadius: 999, border: `1px solid ${PAL.border}`, background: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 17, boxShadow: "0 1px 2px rgba(16,40,30,.04)" };

/* ── pager ─────────────────────────────────────────────────────────────────── */
function Pager({ compact = false, page, totalPages, hasPrev, hasNext, total, count, pageSize, onPage }: { compact?: boolean; page: number; totalPages: number; hasPrev: boolean; hasNext: boolean; total: number; count: number; pageSize: number; onPage: (n: number) => void }) {
  const start = (page - 1) * pageSize + 1;
  const end = (page - 1) * pageSize + count;
  const nums: (number | "…")[] = [];
  const push = (n: number) => nums.push(n);
  if (totalPages <= 7) { for (let i = 1; i <= totalPages; i++) push(i); }
  else {
    push(1);
    if (page > 3) nums.push("…");
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) push(i);
    if (page < totalPages - 2) nums.push("…");
    push(totalPages);
  }
  const numBtn = (active: boolean): CSSProperties => active
    ? { minWidth: 34, height: 34, borderRadius: 9, border: `1px solid ${PAL.mint}`, background: PAL.softmint, color: PAL.emerald, fontSize: 13, fontWeight: 700, cursor: "pointer" }
    : { minWidth: 34, height: 34, borderRadius: 9, border: `1px solid ${PAL.border}`, background: "#fff", color: PAL.text2, fontSize: 13, fontWeight: 500, cursor: "pointer" };
  const edge = (enabled: boolean): CSSProperties => ({ minWidth: 62, height: 34, borderRadius: 9, border: `1px solid ${PAL.border}`, background: "#fff", color: enabled ? PAL.text : PAL.muted, fontSize: 13, fontWeight: 600, cursor: enabled ? "pointer" : "not-allowed", opacity: enabled ? 1 : 0.55 });
  if (compact) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 20, gap: 10 }}>
        <button disabled={!hasPrev} onClick={() => hasPrev && onPage(page - 1)} style={edge(hasPrev)}>‹ Prev</button>
        <div style={{ fontSize: 12.5, color: PAL.muted, textAlign: "center", minWidth: 0 }}>
          <div style={{ color: PAL.text, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{page} / {Math.max(totalPages, 1)}</div>
          <div style={{ fontVariantNumeric: "tabular-nums" }}>{start}-{end} of {total.toLocaleString()}</div>
        </div>
        <button disabled={!hasNext} onClick={() => hasNext && onPage(page + 1)} style={edge(hasNext)}>Next ›</button>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 28, flexWrap: "wrap", gap: 12 }}>
      <div style={{ fontSize: 12.5, color: PAL.muted }}>Showing <span style={{ color: PAL.text, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{start}–{end}</span> of <span style={{ color: PAL.text, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{total.toLocaleString()}</span></div>
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <button disabled={!hasPrev} onClick={() => hasPrev && onPage(page - 1)} style={edge(hasPrev)}>‹ Prev</button>
        {nums.map((n, i) => n === "…" ? <span key={`e${i}`} style={{ color: PAL.muted, padding: "0 4px" }}>…</span> : <button key={n} onClick={() => onPage(n)} style={numBtn(n === page)}>{n}</button>)}
        <button disabled={!hasNext} onClick={() => hasNext && onPage(page + 1)} style={edge(hasNext)}>Next ›</button>
      </div>
    </div>
  );
}

/* ── bits ──────────────────────────────────────────────────────────────────── */
function SkeletonCard() {
  return (
    <div style={{ background: "#fff", border: `1px solid ${PAL.border}`, borderRadius: 16, overflow: "hidden" }}>
      <div style={{ aspectRatio: "4 / 5", background: "linear-gradient(90deg,#EEF2F0 25%,#F6F9F7 50%,#EEF2F0 75%)", backgroundSize: "800px 100%", animation: "fbspyShimmer 1.3s infinite" }} />
      <div style={{ padding: 13 }}>
        <div style={{ height: 13, width: "55%", borderRadius: 6, background: "#EEF2F0", marginBottom: 9 }} />
        <div style={{ height: 11, width: "90%", borderRadius: 6, background: "#F1F4F2", marginBottom: 7 }} />
        <div style={{ height: 11, width: "70%", borderRadius: 6, background: "#F1F4F2" }} />
      </div>
    </div>
  );
}
function Centered({ icon, iconBg, title, sub, children }: { icon: string; iconBg: string; title: string; sub: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 20px", textAlign: "center" }}>
      <div style={{ width: 64, height: 64, borderRadius: 18, background: iconBg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, marginBottom: 16 }}>{icon}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: PAL.head, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13.5, color: PAL.text2, marginBottom: 18, maxWidth: 340 }}>{sub}</div>
      {children}
    </div>
  );
}
function ControlGroup({ label, children, compact = false }: { label: string; children: ReactNode; compact?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flex: compact ? "1 1 auto" : "none" }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: PAL.muted, letterSpacing: ".05em", textTransform: "uppercase" }}>{label}</span>
      {children}
    </div>
  );
}
const Toggle = ({ children }: { children: ReactNode }) => <div style={{ display: "flex", background: "#fff", border: `1px solid ${PAL.border}`, borderRadius: 10, padding: 3, gap: 2 }}>{children}</div>;
function Tbtn({ active, onClick, title, children }: { active: boolean; onClick: () => void; title: string; children: ReactNode }) {
  return <button aria-pressed={active} onClick={onClick} title={title} style={active ? { minWidth: 72, height: 30, borderRadius: 8, border: "none", background: "#E4F6F0", color: "#2E9E73", cursor: "pointer", fontSize: 12.5, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 5, padding: "0 9px" } : { minWidth: 72, height: 30, borderRadius: 8, border: "none", background: "transparent", color: "#8A938E", cursor: "pointer", fontSize: 12.5, fontWeight: 600, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 5, padding: "0 9px" }}>{children}</button>;
}
const filterToggle = (open: boolean): CSSProperties => open
  ? { height: 34, borderRadius: 10, border: `1px solid ${PAL.mint}`, background: PAL.softmint, color: PAL.emerald, cursor: "pointer", flex: "none", fontSize: 12.5, fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 7, padding: "0 11px" }
  : { height: 34, borderRadius: 10, border: `1px solid ${PAL.border}`, background: "#fff", color: PAL.text2, cursor: "pointer", flex: "none", fontSize: 12.5, fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 7, padding: "0 11px" };
const filterCount: CSSProperties = { minWidth: 17, height: 17, borderRadius: 999, background: PAL.emerald, color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700, padding: "0 5px" };
const sortSelect: CSSProperties = { height: 36, border: `1px solid ${PAL.border}`, borderRadius: 10, background: "#fff", padding: "0 30px 0 12px", fontSize: 13, color: PAL.text, outline: "none", cursor: "pointer", appearance: "none", backgroundImage: "url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22><path d=%22M3 4.5L6 7.5L9 4.5%22 stroke=%22%235C6661%22 stroke-width=%221.5%22 fill=%22none%22 stroke-linecap=%22round%22/></svg>')", backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center" };
const primary: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 7, background: "linear-gradient(135deg,#3FBF9A,#2E9E73)", color: "#fff", border: "none", borderRadius: 11, padding: "10px 18px", fontSize: 13.5, fontWeight: 600, cursor: "pointer", boxShadow: "0 4px 14px rgba(46,158,115,.32)" };
const secondary: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 7, background: "#fff", color: PAL.text, border: `1px solid ${PAL.border}`, borderRadius: 11, padding: "10px 18px", fontSize: 13.5, fontWeight: 600, cursor: "pointer" };
