import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { AdFilters, AdFormat, AdType } from "./api/types";
import { countryFlag, languageLabel } from "./lib/media";

const BOOL = (v: string | null): boolean | null => (v === "true" ? true : v === "false" ? false : null);
const TYPE_LABEL: Record<AdType, string> = { link: "Link", in_facebook: "In\u2011Facebook", video: "Video" };

export interface Pill { key: string; group: string; label: string; onRemove: () => void; }

export function useUrlFilters() {
  const [sp, setSp] = useSearchParams();

  const filters: AdFilters = useMemo(() => ({
    q: sp.get("q") || "",
    ad_type: sp.getAll("ad_type") as AdType[],
    format: (sp.get("format") as AdFormat) || null,
    has_landing: BOOL(sp.get("has_landing")),
    screenshot_ok: BOOL(sp.get("screenshot_ok")),
    cloaking: BOOL(sp.get("cloaking")),
    has_video: BOOL(sp.get("has_video")),
    advertiser__search: sp.get("advertiser__search") || "",
    displayed_domain__search: sp.get("displayed_domain__search") || "",
    country: sp.get("country") || null,
    language: sp.get("language") || null,
    vertical: sp.get("vertical") || null,
    platform: sp.get("platform") || null,
    placement: sp.get("placement") || null,
    fb_ad_id: sp.get("fb_ad_id") || "",
    order_by: sp.get("order_by") || "-captured_at",
    page: Number(sp.get("page") || 1),
    page_size: Number(sp.get("page_size") || 24),
  }), [sp]);

  const view = (sp.get("view") as "grid" | "list") || "grid";

  const setMany = (entries: Array<[string, string | null]>, resetPage = true) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of entries) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    if (resetPage) next.set("page", "1");
    setSp(next);
  };
  const set = (k: string, v: string | null, resetPage = true) => setMany([[k, v]], resetPage);

  const toggleAdType = (t: AdType) => {
    const cur = sp.getAll("ad_type");
    const nextVals = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
    const next = new URLSearchParams(sp);
    next.delete("ad_type");
    nextVals.forEach((v) => next.append("ad_type", v));
    next.set("page", "1");
    setSp(next);
  };

  const setView = (v: "grid" | "list") => set("view", v, false);
  const setBool = (k: string, v: boolean | null) => set(k, v === null ? null : String(v));

  const clearAll = () => {
    const next = new URLSearchParams();
    if (filters.order_by) next.set("order_by", filters.order_by);
    if (view) next.set("view", view);
    setSp(next);
  };

  const pills: Pill[] = useMemo(() => {
    const out: Pill[] = [];
    (filters.ad_type || []).forEach((t) =>
      out.push({ key: `type-${t}`, group: "Type:", label: TYPE_LABEL[t], onRemove: () => toggleAdType(t) })
    );
    if (filters.format) out.push({ key: "format", group: "Format:", label: filters.format, onRemove: () => set("format", null) });
    if (filters.has_landing != null)
      out.push({ key: "landing", group: "Landing:", label: filters.has_landing ? "Resolved" : "No landing", onRemove: () => setBool("has_landing", null) });
    if (filters.screenshot_ok != null)
      out.push({ key: "shot", group: "Screenshot:", label: filters.screenshot_ok ? "OK" : "Problem", onRemove: () => setBool("screenshot_ok", null) });
    if (filters.cloaking != null)
      out.push({ key: "cloak", group: "Cloaking:", label: filters.cloaking ? "Suspected" : "Clean", onRemove: () => setBool("cloaking", null) });
    if (filters.advertiser__search) out.push({ key: "adv", group: "Advertiser:", label: filters.advertiser__search, onRemove: () => set("advertiser__search", null) });
    if (filters.displayed_domain__search) out.push({ key: "dom", group: "Domain:", label: filters.displayed_domain__search, onRemove: () => set("displayed_domain__search", null) });
    if (filters.country) out.push({ key: "country", group: "Geo:", label: `${countryFlag(filters.country)} ${filters.country}`, onRemove: () => set("country", null) });
    if (filters.language) out.push({ key: "language", group: "Language:", label: `${filters.language.toUpperCase()} · ${languageLabel(filters.language)}`, onRemove: () => set("language", null) });
    if (filters.vertical) out.push({ key: "vertical", group: "Vertical:", label: filters.vertical, onRemove: () => set("vertical", null) });
    if (filters.placement) out.push({ key: "placement", group: "Placement:", label: filters.placement, onRemove: () => set("placement", null) });
    if (filters.fb_ad_id) out.push({ key: "fbid", group: "FB Ad ID:", label: filters.fb_ad_id, onRemove: () => set("fb_ad_id", null) });
    if (filters.q) out.push({ key: "q", group: "Search:", label: `\u201C${filters.q}\u201D`, onRemove: () => set("q", null) });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  return { filters, view, set, setBool, setMany, toggleAdType, setView, clearAll, pills };
}
