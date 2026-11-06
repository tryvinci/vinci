import type { Config } from "tailwindcss";

/**
 * Utilities only. Studio layout stays in globals.css / brand.css.
 * Colors point at theme.css so a class and a stylesheet stay in sync.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        background: "var(--bg)",
        foreground: "var(--ink)",
        panel: "var(--panel)",
        card: "var(--raised)",
        primary: "var(--teal)",
        "primary-foreground": "var(--btn-ink)",
        muted: "var(--mute)",
        dim: "var(--dim)",
        border: "var(--line)",
        peach: "var(--peach)",
        danger: "var(--danger)",
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        md: "var(--radius-md)",
        pill: "var(--pill)",
      },
      fontFamily: {
        sans: ["var(--font-ui)"],
        display: ["var(--font-display)"],
      },
      boxShadow: {
        card: "var(--card-shadow)",
      },
    },
  },
  plugins: [],
};

export default config;
