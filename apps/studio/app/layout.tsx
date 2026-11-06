import type { ReactNode } from "react";
import { Instrument_Serif, Inter_Tight } from "next/font/google";
import "./globals.css";
import "./theme.css";
import "./brand.css";
import "./tailwind.css";

const interTight = Inter_Tight({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter-tight",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
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
