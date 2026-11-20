"use client";
import { useAuth } from "@/components/auth";

export function AdminOnly({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <p className="p-8 text-center text-sm text-muted-foreground">This page is for administrators.</p>;
  return <>{children}</>;
}
