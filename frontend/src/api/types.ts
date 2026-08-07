export type Role = "admin" | "user";
export type AdType = "link" | "in_facebook" | "video";
export type AdFormat = "image" | "video";

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
}

export interface User {
  id: string;
  username: string;
  role: Role;
  is_active: boolean;
  created_at?: string;
}

export interface Ad {
  id: string;
  run_id: string;
  advertiser: string;
  ad_type: AdType;
  format: AdFormat;
  vertical: string | null;
  country: string | null;
  language: string | null;
  platform: string;
  placement: string;
  cloaking: boolean | null;
  has_video: boolean;
  displayed_domain: string;
  headline: string;
  ad_text: string;
  cta: string;
  creative_img: string | null;
  video_url?: string | null;
  screenshot_url: string | null;
  screenshot_ok: boolean | null;
  screenshot_issue: string | null;
  landing_full: string | null;
  landing_clean: string | null;
  landing_screenshot_url: string | null;
  landing_archive_url: string | null;
  fb_ad_id: string;
  utm: Record<string, string> | null;
  captured_at: string;
  created_at?: string;
  updated_at?: string;
  has_landing?: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface Facet {
  value: string;
  count: number;
}

export interface AdStats {
  total_ads: number;
  link_ads: number;
  resolved_ads: number;
  video_ads: number;
  bad_screenshots: number;
  by_type: Facet[];
  by_format: Facet[];
  by_vertical: Facet[];
  by_country: Facet[];
  by_language: Facet[];
  by_platform: Facet[];
  by_placement: Facet[];
  by_domain: Facet[];
  by_advertiser: Facet[];
  by_cta: Facet[];
}

/** Normalised media item the gallery is built around (future-proof for video). */
export interface MediaItem {
  kind: "screenshot" | "landing" | "creative" | "video";
  type: "image" | "video";
  url: string | null;
  poster?: string | null;
  label: string;
  issue: string | null;
  broken?: boolean;
}

/** Query params accepted by GET /ads. */
export interface AdFilters {
  q?: string;
  ad_type?: AdType[];
  format?: AdFormat | null;
  vertical?: string | null;
  country?: string | null;
  language?: string | null;
  platform?: string | null;
  placement?: string | null;
  cloaking?: boolean | null;
  has_video?: boolean | null;
  screenshot_ok?: boolean | null;
  advertiser__search?: string;
  displayed_domain__search?: string;
  fb_ad_id?: string;
  has_landing?: boolean | null;
  run_id?: string;
  order_by?: string;
  page?: number;
  page_size?: number;
}
