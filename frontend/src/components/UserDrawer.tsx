import { useState, type CSSProperties, type ReactNode } from "react";
import { AxiosError } from "axios";
import type { Role, User } from "../api/types";
import { PAL, MONO, navArrow, primaryBtn, secondaryBtn } from "../theme";
import { useCreateUser, useUpdateUser } from "../api/hooks";
import { useToast } from "../toasts";

type Mode = "create" | "edit" | "self";

export default function UserDrawer({ mode, user, currentUser, onClose }: {
  mode: Mode;
  user?: User;
  currentUser: User;
  onClose: () => void;
}) {
  const toast = useToast();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const isAdmin = currentUser.role === "admin";
  const showRoleControls = isAdmin && mode !== "self";

  const [username, setUsername] = useState(user?.username || "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>(user?.role || "user");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [nameError, setNameError] = useState(false);
  const saving = createUser.isPending || updateUser.isPending;

  const title = mode === "create" ? "Create user" : mode === "self" ? "My account" : "Edit user";

  const save = async () => {
    if (!username.trim()) { toast("Username is required", "error"); return; }
    setNameError(false);
    try {
      if (mode === "create") {
        await createUser.mutateAsync({ username: username.trim(), password, role });
        toast("User created");
      } else {
        const body: Record<string, unknown> = { username: username.trim() };
        if (password) body.password = password;
        if (showRoleControls) { body.role = role; body.is_active = active; }
        await updateUser.mutateAsync({ id: (user as User).id, body });
        toast("Changes saved");
      }
      onClose();
    } catch (e) {
      if (e instanceof AxiosError && e.response?.status === 409) setNameError(true);
      else toast("Could not save user", "error");
    }
  };

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(24,38,40,.32)", zIndex: 60, animation: "fbspyFade .15s ease" }} />
      <div className="fbspy-scroll" style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: 440, maxWidth: "94vw", background: "#fff", zIndex: 61, boxShadow: "-20px 0 60px rgba(16,40,30,.18)", overflow: "auto", animation: "fbspyDrawer .2s ease" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 22px", borderBottom: `1px solid ${PAL.border}` }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: PAL.head }}>{title}</div>
          <button onClick={onClose} style={navArrow}>×</button>
        </div>
        <div style={{ padding: 22 }}>
          <FieldLabel>Username</FieldLabel>
          <input value={username} onChange={(e) => { setUsername(e.target.value); setNameError(false); }} placeholder="username" style={{ ...inp, fontFamily: MONO, marginBottom: 6 }} />
          {nameError && <div style={{ fontSize: 12, color: "#B23B31", marginBottom: 12, display: "flex", gap: 6, alignItems: "center" }}>⚠ Username already taken.</div>}
          <div style={{ height: 14 }} />

          <FieldLabel>{mode === "create" ? "Password" : "Set new password"}</FieldLabel>
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" placeholder={mode === "create" ? "choose a password" : "leave blank to keep current"} style={{ ...inp, marginBottom: 18 }} />

          {showRoleControls && (
            <>
              <FieldLabel>Role</FieldLabel>
              <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
                {(["user", "admin"] as Role[]).map((r) => (
                  <button key={r} onClick={() => setRole(r)} style={role === r
                    ? { flex: 1, padding: 10, borderRadius: 11, border: `1px solid ${PAL.mint}`, background: PAL.softmint, color: PAL.emerald, fontWeight: 600, fontSize: 13, cursor: "pointer" }
                    : { flex: 1, padding: 10, borderRadius: 11, border: `1px solid ${PAL.border}`, background: "#fff", color: PAL.text2, fontWeight: 500, fontSize: 13, cursor: "pointer" }}>
                    {r === "admin" ? "Admin" : "User"}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", background: "#F7FAF9", border: `1px solid ${PAL.border}`, borderRadius: 12, marginBottom: 24 }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: PAL.text }}>Active</div>
                  <div style={{ fontSize: 11.5, color: PAL.muted }}>Inactive users can’t sign in.</div>
                </div>
                <button onClick={() => setActive((a) => !a)} style={{ width: 44, height: 25, borderRadius: 999, border: "none", cursor: "pointer", background: active ? PAL.emerald : "#CBD3CF", position: "relative", transition: "background .15s ease", flex: "none" }}>
                  <span style={{ position: "absolute", top: 3, left: active ? 22 : 3, width: 19, height: 19, borderRadius: 999, background: "#fff", transition: "left .15s ease", boxShadow: "0 1px 3px rgba(0,0,0,.25)" }} />
                </button>
              </div>
            </>
          )}

          {mode === "self" && (
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", background: "#EEF3F4", border: "1px solid #D6E2E5", borderRadius: 11, padding: "11px 13px", marginBottom: 22, fontSize: 12, color: "#456470", lineHeight: 1.45 }}>
              <span>ℹ</span><span>You can update your own username and password. Only an admin can change your role or active status.</span>
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={save} disabled={saving} style={{ ...primaryBtn, flex: 1, justifyContent: "center", opacity: saving ? 0.8 : 1 }}>{mode === "create" ? "Create user" : "Save changes"}</button>
            <button onClick={onClose} style={secondaryBtn}>Cancel</button>
          </div>
        </div>
      </div>
    </>
  );
}

const FieldLabel = ({ children }: { children: ReactNode }) => (
  <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: PAL.text, marginBottom: 6 }}>{children}</label>
);
const inp: CSSProperties = { width: "100%", height: 42, border: `1px solid ${PAL.border}`, borderRadius: 11, padding: "0 14px", fontSize: 14, background: "#FBFCFB", outline: "none" };
