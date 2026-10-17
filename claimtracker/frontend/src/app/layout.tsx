import type { Metadata } from "next";

import { Nav } from "@/components/Nav";
import { AuthProvider } from "@/lib/auth/AuthProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimTracker",
  description:
    "AI-powered health insurance claims processing — OCR, RAG and a human-in-the-loop reviewer queue.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          {/* Keyboard users can jump the nav. */}
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4
                       focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2
                       focus:shadow"
          >
            Skip to content
          </a>
          <Nav />
          <main id="main" className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
            {children}
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
