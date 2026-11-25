import type { ReactNode } from "react";
import localFont from "next/font/local";
import "./globals.css";
import "./theme.css";
import "./brand.css";
import "./tailwind.css";

// Self-hosted latin subset (SIL OFL 1.1, see fonts/OFL-Inter.txt): the build does not fetch
// Google Fonts, so it works offline and cannot fail on a Google reply (COREPRODUC-522).
// Inter variable (weight 100-900, optical size 14-32) is the only face: display = UI at a heavier weight.
const inter = localFont({
  src: [{ path: "./fonts/Inter-latin.woff2", weight: "100 900", style: "normal" }],
  variable: "--font-inter",
  display: "swap",
});

export const metadata = { title: "Vinci Studio" };

export const viewport = { themeColor: "#f4f3f0" };

// Restores the rail theme switch (ui/theme-toggle.tsx) before first paint: Paper unless "graphite" was saved.
const THEME_BOOT = `try{if(localStorage.getItem("vinci-theme")==="graphite")document.documentElement.dataset.theme="graphite"}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body className={inter.className}>{children}</body>
    </html>
  );
}
