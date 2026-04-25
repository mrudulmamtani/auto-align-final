import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "pwc-orange":        "var(--pwc-orange)",
        "pwc-orange-hover":  "var(--pwc-orange-hover)",
        "pwc-bg":            "var(--pwc-bg)",
        "pwc-surface":       "var(--pwc-surface)",
        "pwc-surface-raised":"var(--pwc-surface-raised)",
        "pwc-border":        "var(--pwc-border)",
        "pwc-border-bright": "var(--pwc-border-bright)",
        "pwc-text":          "var(--pwc-text)",
        "pwc-text-dim":      "var(--pwc-text-dim)",
        "pwc-text-muted":    "var(--pwc-text-muted)",
        "risk-critical":     "var(--pwc-critical)",
        "risk-high":         "var(--pwc-high)",
        "risk-medium":       "var(--pwc-medium)",
        "risk-low":          "var(--pwc-low)",
      },
    },
  },
  plugins: [],
};

export default config;
