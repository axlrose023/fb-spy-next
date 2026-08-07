import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { Ad } from "../api/types";
import { PAL, MONO, TYPEMETA, KINDMETA, chip, iconBtn } from "../theme";
import { abs, advColor, buildMedia, countryFlag, countryLabel, downloadMedia, hasLanding, languageLabel, midEllipsis, mono, rel } from "../lib/media";
import { useIsNarrow } from "../lib/responsive";
import { useHorizontalSwipe } from "../lib/useHorizontalSwipe";
import { useCopy, useToast } from "../toasts";
import SafeImage from "./SafeImage";

export default function AdDetail({ ad }: { ad: Ad }) {
  const copy = useCopy();
  const toast = useToast();
  const isMobile = useIsNarrow();
  const media = buildMedia(ad);
  const tm = TYPEMETA[ad.ad_type];
  const [ai, setAi] = useState(0);
  const [lightbox, setLightbox] = useState(false);
  const [textOpen, setTextOpen] = useState(false);
  const [landingOpen, setLandingOpen] = useState(false);
  const [utmOpen, setUtmOpen] = useState<Record<string, boolean>>({});
  const stageScrollRef = useRef<HTMLDivElement | null>(null);
  const lightboxScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { setAi(0); setTextOpen(false); setLandingOpen(false); }, [ad.id]);
  const active = media[Math.min(ai, media.length - 1)];
  const landingMediaIndex = media.findIndex((item) => item.kind === "landing");
  const km = KINDMETA[active.kind] || KINDMETA.screenshot;
  const stepMedia = (dir: number) => {
    setAi((i) => (i + dir + media.length) % media.length);
  };
  const mediaSwipe = useHorizontalSwipe({
    enabled: isMobile && media.length > 1,
    onSwipeLeft: () => stepMedia(1),
    onSwipeRight: () => stepMedia(-1),
  });
  useEffect(() => {
    stageScrollRef.current?.scrollTo({ top: 0, left: 0 });
    lightboxScrollRef.current?.scrollTo({ top: 0, left: 0 });
  }, [ai, ad.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (lightbox) {
        if (e.key === "Escape") setLightbox(false);
        if (e.key === "ArrowRight") setAi((i) => (i + 1) % media.length);
        if (e.key === "ArrowLeft") setAi((i) => (i - 1 + media.length) % media.length);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox, media.length]);

  const landing = hasLanding(ad);
  const utm = ad.utm || {};
  const utmEntries = Object.entries(utm);
  const geoCountry = countryLabel(ad.country);
  const geoFlag = countryFlag(ad.country);
  const handleDownload = async () => {
    try {
      await downloadMedia(active.url || active.poster, `${ad.advertiser || "ad"}-${active.kind}-${ad.id}`);
      toast("Download started", "success");
    } catch {
      toast("Download failed", "error");
    }
  };
  const handleDownloadLandingArchive = async () => {
    try {
      await downloadMedia(ad.landing_archive_url, `${ad.advertiser || "ad"}-landing-${ad.id}`);
      toast("Landing archive download started", "success");
    } catch {
      toast("Landing archive is not available", "error");
    }
  };

  const warnings: { label: string; icon: string; style: CSSProperties }[] = [];
  if (ad.screenshot_ok === false)
    warnings.push({ icon: "⚠", label: `Screenshot QA failed: ${ad.screenshot_issue || "unknown"} — showing what was captured.`, style: banner("#FBE2DF", "#F2C2BD", "#B23B31") });
  if (ad.cloaking === true)
    warnings.push({ icon: "🛡", label: "Possible cloaking detected — landing may differ from what users see.", style: banner("#FAEFD6", "#ECD49B", "#8A6516") });

  const metaChips = [
    { l: ad.platform },
    { l: ad.placement },
    { l: `Geo: ${geoCountry}` },
    ...(ad.language ? [{ l: `Language: ${languageLabel(ad.language)}` }] : []),
    ...(ad.vertical ? [{ l: ad.vertical }] : []),
  ];

  return (
    <div style={{ fontFamily: "'Inter',system-ui,sans-serif", color: PAL.text }}>
      {warnings.map((w, i) => (
        <div key={i} style={w.style}><span style={{ fontSize: 15 }}>{w.icon}</span><span>{w.label}</span></div>
      ))}

      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "minmax(0,1fr)" : "repeat(auto-fit,minmax(320px,1fr))", gap: isMobile ? 16 : 24, alignItems: "start" }}>
        {/* GALLERY */}
        <div>
          <div style={{ position: "relative", background: "repeating-conic-gradient(#EEF2F0 0% 25%,#F6F9F7 0% 50%) 50%/20px 20px", border: `1px solid ${PAL.border}`, borderRadius: isMobile ? 12 : 16, overflow: "hidden", display: "flex", alignItems: "stretch", justifyContent: "center", height: isMobile ? "clamp(330px, 62svh, 520px)" : "clamp(430px, 62vh, 620px)" }}>
            <div style={{ position: "absolute", top: 11, left: 11, zIndex: 3 }}><span style={chip(km.c, km.bg)}>{km.l}</span></div>
            {active.issue && <div style={{ position: "absolute", top: isMobile ? 42 : 11, right: 11, left: isMobile ? 11 : undefined, zIndex: 3, display: "flex", justifyContent: isMobile ? "flex-start" : "flex-end" }}><span style={{ background: "#FBE2DF", color: "#B23B31", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "4px 10px", maxWidth: "100%", whiteSpace: "normal" }}>⚠ {active.issue}</span></div>}
            {media.length > 1 && (
              <>
                <button onClick={(e) => { e.stopPropagation(); stepMedia(-1); }} title="Previous media" style={galleryArrow("left")}>‹</button>
                <button onClick={(e) => { e.stopPropagation(); stepMedia(1); }} title="Next media" style={galleryArrow("right")}>›</button>
                <div style={{ position: "absolute", left: "50%", bottom: 12, transform: "translateX(-50%)", zIndex: 4, background: "rgba(24,38,40,.72)", color: "#fff", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "4px 10px", fontVariantNumeric: "tabular-nums", boxShadow: "0 2px 8px rgba(0,0,0,.18)" }}>{ai + 1} / {media.length}</div>
              </>
            )}

            {active.type === "video" ? (
              <div style={{ position: "relative", width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {active.url ? (
                  <DetailVideo src={active.url} poster={active.poster} />
                ) : (
                  <>
                    <SafeImage src={active.poster} fit="contain" fallbackLabel="Video poster unavailable" style={{ width: "100%", height: "100%", background: "#101816" }} />
                    <div data-testid="video-source-missing" style={{ position: "absolute", left: 14, right: 14, bottom: 14, display: "flex", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
                      <span style={{ background: "rgba(24,38,40,.78)", color: "#fff", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "7px 12px", boxShadow: "0 4px 14px rgba(0,0,0,.22)" }}>Video detected · source not captured</span>
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div ref={stageScrollRef} data-testid="detail-gallery-scroll" data-horizontal-swipe className="fbspy-scroll" {...mediaSwipe} onClick={() => active.url && setLightbox(true)} style={{ height: "100%", overflow: "auto", width: "100%", display: "flex", justifyContent: "center", alignItems: "flex-start", padding: isMobile ? "0 8px 36px" : "0 16px 42px", cursor: active.url ? "zoom-in" : "default", scrollPaddingTop: 0 }}>
                <SafeImage src={active.url} fit="contain" loading="eager" fallbackLabel={`${active.label} unavailable — source may have expired`} style={{ width: "100%", maxWidth: isMobile || active.kind === "landing" ? "100%" : 460, display: "block", borderRadius: 6 }} />
              </div>
            )}
          </div>

          {media.length > 1 && (
            <div style={{ display: "flex", gap: 9, marginTop: 12, flexWrap: "wrap" }}>
              {media.map((m, i) => (
                <button key={i} onClick={() => setAi(i)} title={KINDMETA[m.kind]?.l || m.kind} style={{ position: "relative", width: 62, height: 62, borderRadius: 11, padding: 0, border: i === ai ? `2px solid ${PAL.mint}` : `1px solid ${PAL.border}`, background: "#fff", cursor: "pointer", overflow: "hidden", flex: "none", boxShadow: i === ai ? "0 0 0 3px rgba(63,191,154,.18)" : "none" }}>
                  <SafeImage src={m.poster || m.url} fit="cover" fallbackLabel="" style={{ width: "100%", height: "100%" }} />
                  {m.kind === "video" && <span style={{ position: "absolute", bottom: 3, right: 3, background: "rgba(24,38,40,.82)", color: "#fff", fontSize: 9, fontWeight: 700, borderRadius: 5, padding: "1px 5px" }}>▶</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* FACTS */}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 14 }}>
            <div style={{ width: 40, height: 40, borderRadius: 12, background: advColor(ad.advertiser), color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700, flex: "none" }}>{mono(ad.advertiser)}</div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: isMobile ? 16 : 17, fontWeight: 800, color: PAL.head, letterSpacing: "-.01em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ad.advertiser}</div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 4, flexWrap: "wrap" }}>
                <span style={chip(tm.fg, tm.bg)}>{tm.i} {tm.l}</span>
                {metaChips.map((m, i) => <span key={i} style={{ fontSize: 11, fontWeight: 600, color: PAL.text2, background: PAL.panel, borderRadius: 999, padding: "3px 9px" }}>{m.l}</span>)}
              </div>
            </div>
          </div>

          <div style={{ fontSize: isMobile ? 17 : 19, fontWeight: 700, color: PAL.head, lineHeight: 1.3, marginBottom: 10, letterSpacing: "-.01em" }}>{ad.headline}</div>

          <div style={{ position: "relative", marginBottom: 8 }}>
            <div style={{ fontSize: 13.5, lineHeight: 1.6, color: PAL.text2, whiteSpace: "pre-wrap", ...(ad.ad_text.length > 180 && !textOpen ? { maxHeight: 132, overflow: "hidden" } : {}) }}>{ad.ad_text}</div>
            {ad.ad_text.length > 180 && !textOpen && <div style={{ position: "absolute", left: 0, right: 0, bottom: 24, height: 34, background: "linear-gradient(transparent,#fff)" }} />}
            {ad.ad_text.length > 180 && <button onClick={() => setTextOpen((o) => !o)} style={{ background: "none", border: "none", color: PAL.emerald, fontSize: 12.5, fontWeight: 700, cursor: "pointer", padding: "6px 0 0" }}>{textOpen ? "Show less" : "Show more"}</button>}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "14px 0 18px" }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: PAL.muted, textTransform: "uppercase", letterSpacing: ".06em" }}>Call to action</span>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: PAL.emerald, background: PAL.softmint, border: "1px solid #9FDBC8", borderRadius: 999, padding: "5px 13px" }}>{ad.cta}</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "0 0 18px", padding: "12px 14px", border: "1px solid #D7E8E0", borderRadius: 12, background: "#F4FBF8" }}>
            <div style={{ width: 38, height: 38, borderRadius: 11, background: "#fff", border: "1px solid #BFE8DA", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, flex: "none", lineHeight: 1 }}>{geoFlag}</div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: PAL.muted, textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 3 }}>Target geo</div>
              <div style={{ fontSize: 15, fontWeight: 800, color: PAL.head }}>{geoCountry}</div>
            </div>
            <span style={{ fontSize: 11.5, fontWeight: 700, color: PAL.emerald, background: "#DDF3EB", border: "1px solid #BFE8DA", borderRadius: 999, padding: "4px 9px" }}>Profile</span>
          </div>

          {/* destination */}
          <Panel title="Destination">
            {landing ? (
              <>
                <Label>Landing (clean)</Label>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14, minWidth: 0 }}>
                  <a href={ad.landing_clean ? `https://${ad.landing_clean.replace(/^https?:\/\//, "")}` : "#"} target="_blank" rel="noopener noreferrer" style={{ fontFamily: MONO, fontSize: 12.5, color: PAL.emerald, fontWeight: 600, textDecoration: "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{ad.landing_clean || "—"}</a>
                  <button onClick={() => copy(ad.landing_clean || "")} title="Copy" style={iconBtn}>⧉</button>
                  <button onClick={() => ad.landing_clean && window.open(`https://${ad.landing_clean.replace(/^https?:\/\//, "")}`, "_blank", "noopener")} title="Open" style={iconBtn}>↗</button>
                </div>
                <Label>Full URL (with UTMs)</Label>
                <div style={{ background: "#F7FAF9", border: "1px solid #EBEFED", borderRadius: 10, padding: "9px 11px" }}>
                  <div style={{ fontFamily: MONO, fontSize: 11.5, color: PAL.text2, lineHeight: 1.5, wordBreak: "break-all" }}>
                    {ad.landing_full ? (landingOpen ? ad.landing_full : midEllipsis(ad.landing_full, 64, 42)) : "—"}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                    <button onClick={() => setLandingOpen((o) => !o)} style={linkBtn}>{landingOpen ? "Show less" : "Show full"}</button>
                    <span style={{ color: "#D2DAD6" }}>·</span>
                    <button onClick={() => copy(ad.landing_full || "")} style={{ ...linkBtn, color: PAL.text2 }}>Copy full</button>
                    <span style={{ color: "#D2DAD6" }}>·</span>
                    <button onClick={() => ad.landing_full && window.open(ad.landing_full, "_blank", "noopener")} style={{ ...linkBtn, color: PAL.text2 }}>Open ↗</button>
                  </div>
                </div>
                <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 10, padding: "11px 12px", background: ad.landing_archive_url ? "#F2FBF8" : "#F7FAF9", border: `1px solid ${ad.landing_archive_url ? "#BFE8DA" : "#EBEFED"}`, borderRadius: 10, flexWrap: isMobile ? "wrap" : "nowrap" }}>
                  <div style={{ width: 30, height: 30, borderRadius: 9, background: ad.landing_archive_url ? PAL.softmint : PAL.panel, color: ad.landing_archive_url ? PAL.emerald : PAL.muted, display: "flex", alignItems: "center", justifyContent: "center", flex: "none", fontSize: 14 }}>▣</div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: PAL.head }}>Landing archive</div>
                    <div style={{ fontSize: 11.5, color: PAL.text2, marginTop: 2 }}>{ad.landing_archive_url ? "Offline preview, browser snapshot and page files saved as ZIP" : "Archive has not been collected for this ad yet"}</div>
                  </div>
                  {ad.landing_archive_url && (
                    <button onClick={handleDownloadLandingArchive} title="Download landing archive" style={{ ...iconBtn, width: isMobile ? "100%" : "auto", padding: "0 11px", gap: 6, color: PAL.emerald, borderColor: "#BFE8DA", fontWeight: 800 }}>⬇ ZIP</button>
                  )}
                </div>
                {landingMediaIndex >= 0 && (
                  <button
                    type="button"
                    onClick={() => { setAi(landingMediaIndex); setLightbox(true); }}
                    style={{ ...linkBtn, marginTop: 10, color: PAL.emerald }}
                  >View full-page screenshot</button>
                )}
              </>
            ) : (
              <div style={{ display: "flex", gap: 9, alignItems: "flex-start", color: PAL.text2, fontSize: 12.5, lineHeight: 1.5, background: "#F7FAF9", borderRadius: 10, padding: "11px 13px" }}>
                <span>⌂</span>
                <span>This is an <strong style={{ color: PAL.text }}>In‑Facebook</strong> ad — it stays on Facebook with no external landing page. That’s expected, not an error.</span>
              </div>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, paddingTop: 12, borderTop: `1px solid ${PAL.panel}` }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: PAL.muted, textTransform: "uppercase", letterSpacing: ".05em" }}>Displayed domain</span>
              <span style={{ fontFamily: MONO, fontSize: 12, color: PAL.text, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{ad.displayed_domain}</span>
              <button onClick={() => copy(ad.displayed_domain)} title="Copy" style={iconBtn}>⧉</button>
            </div>
          </Panel>

          {/* UTM */}
          <Panel title={`UTM parameters ${utmEntries.length ? `· ${utmEntries.length} keys` : ""}`}>
            {utmEntries.length === 0 ? (
              <div style={{ fontSize: 12.5, color: PAL.muted }}>No UTM parameters — this ad has no external landing.</div>
            ) : (
              utmEntries.map(([k, v]) => {
                const long = v.length > 44 || k === "fbclid";
                const o = !!utmOpen[k];
                const display = o ? v : k === "fbclid" ? v.slice(0, 16) + "…" : long ? midEllipsis(v, 28, 12) : v;
                return (
                  <div key={k} style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr auto" : "130px 1fr auto", gap: 10, padding: "10px 0", borderBottom: "1px solid #F4F6F5", alignItems: "center" }}>
                    <span style={{ fontFamily: MONO, fontSize: 11.5, color: PAL.text2, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{k}</span>
                    <span style={{ fontFamily: MONO, fontSize: 11.5, color: PAL.text, wordBreak: "break-all", lineHeight: 1.4, gridColumn: isMobile ? "1 / -1" : undefined, gridRow: isMobile ? "2" : undefined }}>
                      {display}
                      {long && <button onClick={() => setUtmOpen((s) => ({ ...s, [k]: !s[k] }))} style={{ background: "none", border: "none", color: PAL.emerald, fontSize: 11, fontWeight: 700, cursor: "pointer", marginLeft: 6, padding: 0 }}>{o ? "collapse" : k === "fbclid" ? "reveal" : "expand"}</button>}
                    </span>
                    <button onClick={() => copy(v)} title="Copy" style={iconBtn}>⧉</button>
                  </div>
                );
              })
            )}
          </Panel>

          {/* technical */}
          <Panel title="Technical" last>
            <Tech label="FB Ad ID" value={ad.fb_ad_id} onCopy={() => copy(ad.fb_ad_id)} />
            <Tech label="Internal ID" value={ad.id} onCopy={() => copy(ad.id)} />
            <Tech label="Run ID" value={ad.run_id} onCopy={() => copy(ad.run_id)} />
            <Tech label="Format" value={ad.format} />
            <Tech label="Captured" value={`${abs(ad.captured_at)}  (${rel(ad.captured_at)})`} />
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0 4px" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: PAL.muted, textTransform: "uppercase", letterSpacing: ".05em", width: 110, flex: "none" }}>Screenshot</span>
              {ad.screenshot_ok === true ? <span style={chip("#2E9E73", "#E4F6F0")}>✓ OK</span> : ad.screenshot_ok === false ? <span style={chip("#B23B31", "#FBE2DF")}>⚠ {ad.screenshot_issue || "problem"}</span> : <span style={chip(PAL.muted, PAL.panel)}>— Unknown</span>}
            </div>
          </Panel>
        </div>
      </div>

      {/* LIGHTBOX */}
      {lightbox && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(16,24,22,.92)", zIndex: 90, display: "flex", flexDirection: "column", animation: "fbspyFade .15s ease" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: isMobile ? "10px 12px" : "14px 18px", color: "#fff", flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{active.label}</span>
            <div style={{ flex: 1 }} />
            <button onClick={handleDownload} style={lbBtn}>⬇ Download</button>
            <button onClick={() => setLightbox(false)} style={lbBtn}>× Close</button>
          </div>
          <div data-testid="detail-lightbox-stage" data-horizontal-swipe {...mediaSwipe} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: isMobile ? "0 12px 18px" : "0 48px 24px", position: "relative", overflow: "hidden" }}>
            {media.length > 1 && <button onClick={() => stepMedia(-1)} style={lbArrow("left")}>‹</button>}
            <div ref={lightboxScrollRef} className="fbspy-scroll" style={{ maxHeight: "100%", width: active.kind === "landing" ? "100%" : "auto", maxWidth: isMobile ? "100%" : active.kind === "landing" ? 1240 : 520, overflow: "auto", borderRadius: active.kind === "landing" ? 8 : 14, boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}>
              <SafeImage src={active.url || active.poster} fit="contain" loading="eager" fallbackLabel="Source unavailable" style={{ width: active.kind === "landing" ? "100%" : 480, maxWidth: "92vw", display: "block", background: "#fff" }} />
            </div>
            {media.length > 1 && <button onClick={() => stepMedia(1)} style={lbArrow("right")}>›</button>}
          </div>
        </div>
      )}
    </div>
  );
}

function DetailVideo({ src, poster }: { src: string; poster?: string | null }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    video?.pause();
    try {
      if (video) video.currentTime = 0;
    } catch {
      // Some browser/video combinations reject seeking before metadata is ready.
    }
    setPlaying(false);
    setHovered(false);
  }, [src]);

  const toggle = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused || video.ended) {
      try {
        await video.play();
      } catch {
        setPlaying(false);
      }
    } else {
      video.pause();
    }
  };

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ position: "relative", width: "100%", height: "100%", background: "#101816" }}
    >
      <video
        ref={videoRef}
        src={src}
        poster={poster || undefined}
        controls
        playsInline
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onLoadedMetadata={(e) => setPlaying(!e.currentTarget.paused && !e.currentTarget.ended)}
        style={{ width: "100%", height: "100%", objectFit: "contain", background: "#101816", display: "block" }}
      />
      <button
        type="button"
        onClick={toggle}
        title={playing ? "Pause video" : "Play video"}
        aria-label={playing ? "Pause video" : "Play video"}
        style={videoPlayBtn(playing, hovered)}
      >
        <span style={{ fontSize: playing ? 20 : 25, lineHeight: 1, marginLeft: playing ? 0 : 4 }}>{playing ? "Ⅱ" : "▶"}</span>
      </button>
    </div>
  );
}

function Panel({ title, children, last }: { title: string; children: ReactNode; last?: boolean }) {
  return (
    <div style={{ border: `1px solid ${PAL.border}`, borderRadius: 14, overflow: "hidden", marginBottom: last ? 0 : 14 }}>
      <div style={{ padding: "11px 14px", background: "#F7FAF9", borderBottom: `1px solid ${PAL.border}`, fontSize: 12, fontWeight: 700, color: PAL.head, display: "flex", alignItems: "center", gap: 7 }}>{title}</div>
      <div style={{ padding: title === "Technical" ? "6px 14px 12px" : 14 }}>{children}</div>
    </div>
  );
}
const Label = ({ children }: { children: ReactNode }) => (
  <div style={{ fontSize: 11, fontWeight: 700, color: PAL.muted, textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>{children}</div>
);
function Tech({ label, value, onCopy }: { label: string; value: string; onCopy?: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid #F4F6F5" }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: PAL.muted, textTransform: "uppercase", letterSpacing: ".05em", width: 110, flex: "none" }}>{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 11.5, color: PAL.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{value}</span>
      {onCopy && <button onClick={onCopy} title="Copy" style={iconBtn}>⧉</button>}
    </div>
  );
}

const linkBtn: CSSProperties = { background: "none", border: "none", color: PAL.emerald, fontSize: 11.5, fontWeight: 700, cursor: "pointer", padding: 0 };
const lbBtn: CSSProperties = { background: "rgba(255,255,255,.14)", color: "#fff", border: "none", borderRadius: 10, padding: "8px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer" };
const lbArrow = (side: "left" | "right"): CSSProperties => ({ position: "absolute", [side]: 18, top: "50%", transform: "translateY(-50%)", width: 46, height: 46, borderRadius: 999, border: "none", background: "rgba(255,255,255,.14)", color: "#fff", fontSize: 22, cursor: "pointer" });
const galleryArrow = (side: "left" | "right"): CSSProperties => ({ position: "absolute", [side]: 12, top: "50%", transform: "translateY(-50%)", zIndex: 4, width: 36, height: 36, borderRadius: 999, border: "1px solid rgba(255,255,255,.82)", background: "rgba(255,255,255,.92)", color: PAL.text, fontSize: 20, cursor: "pointer", boxShadow: "0 4px 14px rgba(16,40,30,.18)", display: "inline-flex", alignItems: "center", justifyContent: "center" });
const videoPlayBtn = (playing: boolean, hovered: boolean): CSSProperties => ({
  position: "absolute",
  left: "50%",
  top: "50%",
  transform: "translate(-50%,-50%)",
  zIndex: 3,
  width: playing ? 58 : 72,
  height: playing ? 58 : 72,
  borderRadius: 999,
  border: "1px solid rgba(255,255,255,.78)",
  background: playing ? "rgba(24,38,40,.66)" : "rgba(255,255,255,.94)",
  color: playing ? "#fff" : "#182628",
  boxShadow: "0 10px 28px rgba(0,0,0,.28)",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
  opacity: playing && !hovered ? 0 : 1,
  pointerEvents: playing && !hovered ? "none" : "auto",
  backdropFilter: "blur(3px)",
  transition: "opacity .16s ease, transform .16s ease, background .16s ease, width .16s ease, height .16s ease",
});
const banner = (bg: string, bd: string, fg: string): CSSProperties => ({ display: "flex", gap: 9, alignItems: "center", background: bg, border: `1px solid ${bd}`, color: fg, borderRadius: 12, padding: "11px 14px", fontSize: 13, fontWeight: 600, marginBottom: 14 });
