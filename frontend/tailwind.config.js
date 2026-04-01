/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        deep: "#080c14",
        base: "#0f172a",
        card: "#1a2236",
        elevated: "#1e293b",
        input: "#0d1424",
        border: "#283348",
        "border-focus": "#6366f1",
        "text-primary": "#e2e8f0",
        "text-secondary": "#8896b0",
        "text-muted": "#5a6a84",
        accent: "#818cf8",
        "accent-glow": "rgba(129,140,248,0.15)",
        "score-high": "#22c55e",
        "score-mid": "#f59e0b",
        "score-low": "#ef4444",
        "delta-pos": "#22c55e",
        "delta-neg": "#ef4444",
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
    },
  },
  plugins: [],
};
