"use client";

import { createContext, useContext, useEffect } from "react";
import useSWR from "swr";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, fetcher, type User } from "@/lib/api";

interface AuthCtx {
  user: User;
  isAdmin: boolean;
  refresh: () => void;
}
const Ctx = createContext<AuthCtx | null>(null);

export function useAuth(): AuthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthGate");
  return v;
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { data, error, mutate } = useSWR<User>("/auth/me", fetcher, { shouldRetryOnError: false, revalidateOnFocus: true });

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [error, pathname, router]);

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        {error && !(error instanceof ApiError && error.status === 401) ? "Cannot reach the server." : "Loading..."}
      </div>
    );
  }
  return <Ctx.Provider value={{ user: data, isAdmin: data.role === "admin", refresh: () => mutate() }}>{children}</Ctx.Provider>;
}
