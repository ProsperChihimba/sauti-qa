import type { Metadata } from "next";
import { Toaster } from "sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sauti QA",
  description: "AI quality assurance for Swahili call centres",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        {children}
        <Toaster richColors position="top-right" closeButton />
      </body>
    </html>
  );
}
