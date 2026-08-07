import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { endpoints, tokenStore } from "./client";
import type { AdFilters, Role } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: endpoints.me,
    enabled: tokenStore.isAuthed(),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAds(filters: AdFilters) {
  return useQuery({
    queryKey: ["ads", filters],
    queryFn: () => endpoints.ads(filters),
    placeholderData: keepPreviousData,
  });
}

export function useAd(id: string | undefined) {
  return useQuery({
    queryKey: ["ad", id],
    queryFn: () => endpoints.ad(id as string),
    enabled: !!id,
  });
}

export function useStats() {
  return useQuery({ queryKey: ["stats"], queryFn: endpoints.stats, staleTime: 60_000 });
}

export function useUsers(params: { username?: string; role?: Role | ""; page?: number; page_size?: number }) {
  return useQuery({ queryKey: ["users", params], queryFn: () => endpoints.users(params) });
}

export function useLogin() {
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      endpoints.login(username, password),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: endpoints.createUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof endpoints.updateUser>[1] }) =>
      endpoints.updateUser(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
