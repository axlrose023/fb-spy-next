import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import type { Ad, AdFilters, AdStats, Page, Role, Tokens, User } from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || "/api";

/* ── token storage (localStorage) ─────────────────────────────────────────── */
const ACCESS = "fbspy.access";
const REFRESH = "fbspy.refresh";

export const tokenStore = {
  access: () => localStorage.getItem(ACCESS),
  refresh: () => localStorage.getItem(REFRESH),
  set(t: Tokens) {
    localStorage.setItem(ACCESS, t.access_token);
    localStorage.setItem(REFRESH, t.refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  },
  isAuthed: () => !!localStorage.getItem(ACCESS),
};

/* ── axios instance ───────────────────────────────────────────────────────── */
export const api = axios.create({ baseURL: BASE_URL });

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const t = tokenStore.access();
  if (t) config.headers.set("Authorization", `Bearer ${t}`);
  return config;
});

/* Single-flight refresh: queue concurrent 401s behind one refresh call. */
let refreshing: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  const rt = tokenStore.refresh();
  if (!rt) return null;
  try {
    const { data } = await axios.post<Tokens>(`${BASE_URL}/auth/refresh`, { refresh_token: rt });
    tokenStore.set(data);
    return data.access_token;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = error.response?.status;
    const isAuthCall = original?.url?.includes("/auth/");

    if (status === 401 && original && !original._retry && !isAuthCall) {
      original._retry = true;
      refreshing = refreshing || doRefresh();
      const token = await refreshing;
      refreshing = null;
      if (token) {
        original.headers.set("Authorization", `Bearer ${token}`);
        return api(original);
      }
      tokenStore.clear();
      if (location.pathname !== "/login") location.assign("/login");
    }
    return Promise.reject(error);
  }
);

/* ── query param serialisation for GET /ads ───────────────────────────────── */
function buildParams(f: AdFilters): URLSearchParams {
  const p = new URLSearchParams();
  const put = (k: string, v: unknown) => {
    if (v === undefined || v === null || v === "") return;
    p.append(k, String(v));
  };
  put("q", f.q);
  (f.ad_type || []).forEach((t) => p.append("ad_type", t));
  put("format", f.format ?? undefined);
  put("vertical", f.vertical ?? undefined);
  put("country", f.country ?? undefined);
  put("language", f.language ?? undefined);
  put("platform", f.platform ?? undefined);
  put("placement", f.placement ?? undefined);
  if (f.cloaking != null) put("cloaking", f.cloaking);
  if (f.has_video != null) put("has_video", f.has_video);
  if (f.screenshot_ok != null) put("screenshot_ok", f.screenshot_ok);
  put("advertiser__search", f.advertiser__search);
  put("displayed_domain__search", f.displayed_domain__search);
  put("fb_ad_id", f.fb_ad_id);
  if (f.has_landing != null) put("has_landing", f.has_landing);
  put("run_id", f.run_id);
  put("order_by", f.order_by || "-captured_at");
  put("page", f.page || 1);
  put("page_size", f.page_size || 24);
  return p;
}

/* ── endpoints ────────────────────────────────────────────────────────────── */
export const endpoints = {
  login: (username: string, password: string) =>
    axios.post<Tokens>(`${BASE_URL}/auth/login`, { username, password }).then((r) => r.data),
  me: () => api.get<User>("/users/me").then((r) => r.data),
  ads: (f: AdFilters) => api.get<Page<Ad>>("/ads", { params: buildParams(f) }).then((r) => r.data),
  ad: (id: string) => api.get<Ad>(`/ads/${id}`).then((r) => r.data),
  stats: () => api.get<AdStats>("/stats/ads").then((r) => r.data),
  users: (params: { username?: string; role?: Role | ""; page?: number; page_size?: number }) =>
    api.get<Page<User>>("/users", {
      params: Object.fromEntries(
        Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
      ),
    }).then((r) => r.data),
  createUser: (body: { username: string; password: string; role: Role }) =>
    api.post<User>("/users", body).then((r) => r.data),
  updateUser: (id: string, body: Partial<{ username: string; password: string; role: Role; is_active: boolean }>) =>
    api.patch<User>(`/users/${id}`, body).then((r) => r.data),
};
