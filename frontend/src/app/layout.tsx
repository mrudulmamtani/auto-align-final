import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Controls Intelligence Hub — PwC",
  description: "PwC Controls Intelligence Hub — UCCF Semantic Mapping Engine",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ background: "var(--pwc-bg)", color: "var(--pwc-text)", height: "100vh", overflow: "hidden" }}>
        {children}
      </body>
    </html>
  );
}
