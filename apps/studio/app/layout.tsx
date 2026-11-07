import type { ReactNode } from "react";
import localFont from "next/font/local";
import "./globals.css";
import "./theme.css";
import "./brand.css";
import "./tailwind.css";

// Self-hosted latin subsets (SIL OFL 1.1, see fonts/OFL-*.txt): the build does not fetch
// Google Fonts, so it works offline and cannot fail on a Google reply (COREPRODUC-522).
const interTight = localFont({
  src: [{ path: "./fonts/InterTight-latin.woff2", weight: "400 700", style: "normal" }],
  variable: "--font-inter-tight",
  display: "swap",
});

const instrumentSerif = localFont({
  src: [
    { path: "./fonts/InstrumentSerif-Regular-latin.woff2", weight: "400", style: "normal" },
    { path: "./fonts/InstrumentSerif-Italic-latin.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-instrument-serif",
  display: "swap",
  adjustFontFallback: "Times New Roman",
});

export const metadata = { title: "Vinci Studio" };

export const viewport = { themeColor: "#0c0e0e" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${interTight.variable} ${instrumentSerif.variable}`}>
      <body className={interTight.className}>{children}</body>
    </html>
  );
}
