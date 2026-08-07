import type { Ad, MediaItem } from "../api/types";
import { COLORS } from "../theme";

/** Initials for an advertiser monogram. */
export function mono(name: string): string {
  const p = (name || "").trim().split(/\s+/);
  return (((p[0] || "")[0] || "") + ((p[1] || "")[0] || (p[0] || "")[1] || "")).toUpperCase();
}

/** Deterministic monogram colour from the advertiser string. */
export function advColor(name: string): string {
  let h = 0;
  for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return COLORS[h % COLORS.length];
}

/** Relative time, e.g. "2d ago". */
export function rel(iso: string): string {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60000), h = Math.floor(m / 60), day = Math.floor(h / 24);
  if (day > 0) return `${day}d ago`;
  if (h > 0) return `${h}h ago`;
  if (m > 0) return `${m}m ago`;
  return "just now";
}

/** Absolute UTC stamp. */
export function abs(iso: string): string {
  try {
    const d = new Date(iso);
    return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
  } catch {
    return iso;
  }
}

/** Middle-ellipsis for very long URLs / fbclid. */
export function midEllipsis(s: string, head: number, tail: number): string {
  if (!s) return "";
  if (s.length <= head + tail + 1) return s;
  return s.slice(0, head) + "\u2026" + s.slice(-tail);
}

export function hasLanding(ad: Ad): boolean {
  if (typeof ad.has_landing === "boolean") return ad.has_landing;
  return ad.ad_type !== "in_facebook" && !!ad.landing_clean;
}

export function landingUrl(ad: Ad): string {
  return ad.landing_full || ad.landing_clean || "";
}

export function countryLabel(country: string | null | undefined): string {
  return country?.trim() || "Unknown";
}

export function countryFlag(country: string | null | undefined): string {
  const label = countryLabel(country);
  const value = normalizeCountryName(label);
  const code = label.length === 2
    ? label.toUpperCase()
    : COUNTRY_CODES[value] || "";
  if (!/^[A-Z]{2}$/.test(code)) return "🌐";
  const base = 127397;
  return String.fromCodePoint(...[...code].map((char) => char.charCodeAt(0) + base));
}

const COUNTRY_CODES: Record<string, string> = {
  argentina: "AR",
  australia: "AU",
  austria: "AT",
  belgium: "BE",
  brazil: "BR",
  canada: "CA",
  chile: "CL",
  colombia: "CO",
  czechia: "CZ",
  "czech republic": "CZ",
  denmark: "DK",
  egypt: "EG",
  finland: "FI",
  france: "FR",
  germany: "DE",
  greece: "GR",
  hungary: "HU",
  india: "IN",
  indonesia: "ID",
  italy: "IT",
  malaysia: "MY",
  mexico: "MX",
  netherlands: "NL",
  "new zealand": "NZ",
  norway: "NO",
  peru: "PE",
  philippines: "PH",
  pilipinas: "PH",
  poland: "PL",
  portugal: "PT",
  romania: "RO",
  "saudi arabia": "SA",
  "south africa": "ZA",
  spain: "ES",
  espana: "ES",
  sweden: "SE",
  switzerland: "CH",
  thailand: "TH",
  turkey: "TR",
  turkiye: "TR",
  "united arab emirates": "AE",
  uae: "AE",
  "united kingdom": "GB",
  uk: "GB",
  "united states": "US",
  usa: "US",
  vietnam: "VN",
};

function normalizeCountryName(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();
}

const LANGUAGE_LABELS: Record<string, string> = {
  ar: "Arabic",
  bg: "Bulgarian",
  cs: "Czech",
  da: "Danish",
  de: "German",
  el: "Greek",
  en: "English",
  es: "Spanish",
  fil: "Filipino",
  fi: "Finnish",
  fr: "French",
  hi: "Hindi",
  hr: "Croatian",
  hu: "Hungarian",
  id: "Indonesian",
  it: "Italian",
  ja: "Japanese",
  ko: "Korean",
  ms: "Malay",
  nl: "Dutch",
  no: "Norwegian",
  pl: "Polish",
  pt: "Portuguese",
  ro: "Romanian",
  ru: "Russian",
  sk: "Slovak",
  sv: "Swedish",
  th: "Thai",
  tr: "Turkish",
  uk: "Ukrainian",
  vi: "Vietnamese",
  zh: "Chinese",
};

export function languageLabel(language: string | null | undefined): string {
  const code = language?.trim().toLowerCase() || "";
  return LANGUAGE_LABELS[code] || (code ? code.toUpperCase() : "Unknown");
}

export async function downloadMedia(url: string | null | undefined, filenameBase: string): Promise<void> {
  if (!url) throw new Error("No media URL");
  const fallbackName = filenameWithExtension(filenameBase, extensionFromUrl(url));

  try {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`Download failed: ${response.status}`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const filename = filenameWithExtension(filenameBase, extensionFromBlob(blob, url));
    clickDownload(objectUrl, filename);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  } catch {
    clickDownload(url, fallbackName);
  }
}

function filenameWithExtension(filenameBase: string, extension: string): string {
  const base = sanitizeFilename(filenameBase) || "fb-spy-media";
  if (!extension || base.toLowerCase().endsWith(extension.toLowerCase())) return base;
  return `${base}${extension}`;
}

function clickDownload(href: string, filename: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function sanitizeFilename(value: string): string {
  return value
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 96);
}

function extensionFromBlob(blob: Blob, url: string): string {
  if (blob.type === "image/png") return ".png";
  if (blob.type === "image/jpeg") return ".jpg";
  if (blob.type === "image/webp") return ".webp";
  if (blob.type === "video/mp4") return ".mp4";
  if (blob.type === "video/webm") return ".webm";
  return extensionFromUrl(url);
}

function extensionFromUrl(url: string): string {
  try {
    const pathname = new URL(url, window.location.origin).pathname;
    const match = pathname.match(/\.[a-z0-9]{2,5}$/i);
    return match?.[0] || "";
  } catch {
    const clean = url.split(/[?#]/)[0];
    const match = clean.match(/\.[a-z0-9]{2,5}$/i);
    return match?.[0] || "";
  }
}

function looksLikeVideoUrl(url: string | null | undefined): boolean {
  return !!url && /\.(mp4|webm|mov|m4v)(\?|#|$)|\.m3u8(\?|#|$)/i.test(url);
}

/**
 * Derive the normalised media[] array from the current ad fields.
 * Adapter note: until the backend returns media[], we build it here from
 * screenshot_url -> screenshot, landing_screenshot_url -> landing,
 * creative_img -> creative, and video_url -> playable video when available.
 * The UI is written purely against this array.
 */
export function buildMedia(ad: Ad): MediaItem[] {
  const m: MediaItem[] = [];
  const videoUrl = ad.video_url || (looksLikeVideoUrl(ad.creative_img) ? ad.creative_img : null);
  const poster = ad.screenshot_url || (looksLikeVideoUrl(ad.creative_img) ? null : ad.creative_img) || null;
  if (ad.has_video || ad.format === "video") {
    m.push({ kind: "video", type: "video", url: videoUrl, poster, label: "Ad video", issue: null });
  }
  if (ad.screenshot_url) {
    m.push({
      kind: "screenshot", type: "image", url: ad.screenshot_url, label: "Ad screenshot",
      issue: ad.screenshot_ok === false ? (ad.screenshot_issue || "screenshot issue") : null,
      broken: ad.screenshot_ok === false,
    });
  }
  if (ad.landing_screenshot_url) {
    m.push({ kind: "landing", type: "image", url: ad.landing_screenshot_url, label: "Full landing page", issue: null });
  }
  if (ad.creative_img) {
    m.push({ kind: "creative", type: "image", url: ad.creative_img, label: "Original creative", issue: null });
  }
  if (m.length === 0) {
    m.push({ kind: "screenshot", type: "image", url: null, label: "Ad screenshot", issue: ad.screenshot_issue ?? null, broken: true });
  }
  return m;
}

/** Primary media for the card thumbnail (video poster wins, else first image). */
export function primaryMedia(ad: Ad): MediaItem {
  const media = buildMedia(ad);
  const vid = media.find((x) => x.kind === "video");
  if (vid && vid.poster) return vid;
  return media.find((x) => x.type === "image" && !x.broken) || media[0];
}
