import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { CSSProperties } from "react";

type ToastType = "success" | "error";
interface Toast { id: number; msg: string; type: ToastType; }

const Ctx = createContext<(msg: string, type?: ToastType) => void>(() => {});

let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = (msg: string, type: ToastType = "success") => {
    const id = ++seq;
    setToasts((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2200);
  };

  return (
    <Ctx.Provider value={toast}>
      {children}
      <div
        style={{
          position: "fixed", bottom: 22, left: "50%", transform: "translateX(-50%)", zIndex: 120,
          display: "flex", flexDirection: "column", gap: 8, alignItems: "center", pointerEvents: "none",
        }}
      >
        {toasts.map((t) => (
          <div key={t.id} style={toastStyle(t.type)}>
            <span style={{ fontSize: 14 }}>{t.type === "error" ? "⚠" : "✓"}</span>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

function toastStyle(type: ToastType): CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: 9,
    background: type === "error" ? "#3A2422" : "#182628", color: "#fff",
    borderRadius: 12, padding: "11px 16px", fontSize: 13, fontWeight: 500,
    boxShadow: "0 10px 30px rgba(0,0,0,.25)", animation: "fbspyToastIn .2s ease", pointerEvents: "auto",
  };
}

export function useToast() {
  return useContext(Ctx);
}

/** Copy to clipboard + toast. */
export function useCopy() {
  const toast = useToast();
  return useCallback(
    async (text: string | null | undefined) => {
      const value = (text || "").trim();
      if (!value) {
        toast("Nothing to copy", "error");
        return false;
      }
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
        } else {
          fallbackCopy(value);
        }
        toast("Copied to clipboard", "success");
        return true;
      } catch {
        try {
          fallbackCopy(value);
          toast("Copied to clipboard", "success");
          return true;
        } catch {
          toast("Copy failed", "error");
          return false;
        }
      }
    },
    [toast]
  );
}

function fallbackCopy(text: string) {
  const el = document.createElement("textarea");
  el.value = text;
  el.setAttribute("readonly", "");
  el.style.position = "fixed";
  el.style.left = "-9999px";
  document.body.appendChild(el);
  el.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(el);
  if (!ok) throw new Error("copy failed");
}
