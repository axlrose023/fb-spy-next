import { useState, type CSSProperties } from "react";
import type { Role, User } from "../api/types";
import { PAL, MONO, primaryBtn } from "../theme";
import { mono } from "../lib/media";
import { useIsNarrow } from "../lib/responsive";
import { useUsers } from "../api/hooks";
import { useAuth } from "../auth";
import UserDrawer from "../components/UserDrawer";

type DrawerState = { mode: "create" | "edit"; user?: User } | null;

export default function Users() {
  const { user: me } = useAuth();
  const isMobile = useIsNarrow();
  const [roleFilter, setRoleFilter] = useState<"all" | Role>("all");
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const q = useUsers({ role: roleFilter === "all" ? "" : roleFilter, page: 1, page_size: 100 });
  const items = q.data?.items || [];

  return (
    <div style={{ padding: isMobile ? "16px 12px 42px" : "26px 30px 60px", maxWidth: 980 }}>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 22, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: PAL.head, letterSpacing: "-.02em", margin: "0 0 4px" }}>Users</h1>
          <p style={{ fontSize: 13.5, color: PAL.text2, margin: 0 }}>Manage who can access the console.</p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", width: isMobile ? "100%" : "auto" }}>
          <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as "all" | Role)} style={{ ...roleSelect, flex: isMobile ? 1 : "none" }}>
            <option value="all">All roles</option>
            <option value="admin">Admin</option>
            <option value="user">User</option>
          </select>
          <button onClick={() => setDrawer({ mode: "create" })} style={primaryBtn}>+ Create user</button>
        </div>
      </div>

      <div className="fbspy-scroll" style={{ background: "#fff", border: `1px solid ${PAL.border}`, borderRadius: 16, overflowX: "auto", overflowY: "hidden", boxShadow: "0 1px 2px rgba(16,40,30,.04),0 6px 20px rgba(16,40,30,.05)" }}>
        <div style={{ minWidth: 640 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.6fr 110px 110px 130px 70px", gap: 0, padding: "12px 20px", background: "#F7FAF9", borderBottom: `1px solid ${PAL.border}`, fontSize: 11, fontWeight: 700, color: PAL.muted, letterSpacing: ".05em", textTransform: "uppercase" }}>
          <div>Username</div><div>Role</div><div>Status</div><div>Created</div><div />
        </div>
        {q.isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: PAL.muted, fontSize: 13 }}>Loading users…</div>
        ) : items.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: PAL.muted, fontSize: 13 }}>No users match.</div>
        ) : (
          items.map((u) => {
            const isSelf = u.id === me?.id;
            return (
              <div key={u.id} className="fbspy-row" style={{ display: "grid", gridTemplateColumns: "1.6fr 110px 110px 130px 70px", gap: 0, padding: "13px 20px", borderBottom: "1px solid #F1F4F2", alignItems: "center", transition: "background .12s ease" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
                  <div style={{ width: 32, height: 32, borderRadius: 999, background: u.role === "admin" ? PAL.emerald : PAL.slate, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, flex: "none" }}>{mono(u.username)}</div>
                  <span style={{ fontFamily: MONO, fontSize: 13, color: PAL.head, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {u.username}
                    {isSelf && <span style={{ fontFamily: "'Inter'", fontSize: 10.5, color: PAL.emerald, background: PAL.softmint, borderRadius: 999, padding: "2px 7px", marginLeft: 8, fontWeight: 600 }}>you</span>}
                  </span>
                </div>
                <div><span style={u.role === "admin" ? rolePill(true) : rolePill(false)}>{u.role}</span></div>
                <div><span style={u.is_active ? statusActive : statusInactive}>{u.is_active ? "Active" : "Inactive"}</span></div>
                <div style={{ fontSize: 12.5, color: PAL.text2 }}>{(u.created_at || "").slice(0, 10) || "—"}</div>
                <div style={{ textAlign: "right" }}>
                  <button onClick={() => setDrawer({ mode: "edit", user: u })} style={{ background: "none", border: `1px solid ${PAL.border}`, color: PAL.text2, borderRadius: 9, padding: "6px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Edit</button>
                </div>
              </div>
            );
          })
        )}
        </div>
      </div>

      {drawer && me && (
        <UserDrawer
          mode={drawer.mode}
          user={drawer.user}
          currentUser={me}
          onClose={() => setDrawer(null)}
        />
      )}
    </div>
  );
}

const roleSelect: CSSProperties = { height: 40, border: `1px solid ${PAL.border}`, borderRadius: 11, background: "#fff", padding: "0 30px 0 12px", fontSize: 13, color: PAL.text, outline: "none", cursor: "pointer", appearance: "none", backgroundImage: "url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 12 12%22><path d=%22M3 4.5L6 7.5L9 4.5%22 stroke=%22%235C6661%22 stroke-width=%221.5%22 fill=%22none%22 stroke-linecap=%22round%22/></svg>')", backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center" };
const rolePill = (admin: boolean): CSSProperties => admin
  ? { fontSize: 11, fontWeight: 700, color: PAL.emerald, background: PAL.softmint, border: "1px solid #9FDBC8", borderRadius: 999, padding: "3px 10px", display: "inline-block" }
  : { fontSize: 11, fontWeight: 600, color: PAL.text2, background: PAL.panel, border: `1px solid ${PAL.border}`, borderRadius: 999, padding: "3px 10px", display: "inline-block" };
const statusActive: CSSProperties = { fontSize: 11, fontWeight: 600, color: PAL.emerald, background: PAL.softmint, borderRadius: 999, padding: "3px 10px", display: "inline-flex", alignItems: "center", gap: 5 };
const statusInactive: CSSProperties = { fontSize: 11, fontWeight: 600, color: PAL.muted, background: PAL.panel, borderRadius: 999, padding: "3px 10px", display: "inline-block" };
