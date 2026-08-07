import { createContext, useCallback, useContext, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { endpoints, tokenStore } from "./api/client";
import { useMe } from "./api/hooks";
import type { User } from "./api/types";

interface AuthValue {
  user: User | undefined;
  isLoading: boolean;
  isAuthed: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const me = useMe();

  const login = useCallback(
    async (username: string, password: string) => {
      const tokens = await endpoints.login(username, password);
      tokenStore.set(tokens);
      await qc.invalidateQueries({ queryKey: ["me"] });
      await qc.refetchQueries({ queryKey: ["me"] });
    },
    [qc]
  );

  const logout = useCallback(() => {
    tokenStore.clear();
    qc.clear();
    navigate("/login");
  }, [qc, navigate]);

  return (
    <Ctx.Provider
      value={{
        user: me.data,
        isLoading: me.isLoading,
        isAuthed: tokenStore.isAuthed(),
        login,
        logout,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}
