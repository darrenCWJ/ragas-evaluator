/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // "Instrument" theme — graphite engineering-lab surfaces, cyan signal
      // accent. Score colors stay semantic (green/amber/red) and the accent
      // deliberately avoids them.
      colors: {
        deep: "#090d12",
        base: "#0d131b",
        card: "#131b26",
        elevated: "#1a2532",
        input: "#0a1018",
        border: "#223144",
        "border-focus": "#22d3ee",
        "text-primary": "#e8eef5",
        "text-secondary": "#93a5ba",
        "text-muted": "#5c6f85",
        accent: "#22d3ee",
        "accent-glow": "rgba(34,211,238,0.14)",
        "score-high": "#34d399",
        "score-mid": "#fbbf24",
        "score-low": "#f87171",
        "delta-pos": "#34d399",
        "delta-neg": "#f87171",
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],   // 10px
        "micro": ["0.6875rem", { lineHeight: "1rem" }],     // 11px
      },
      fontFamily: {
        sans: ['"Inter"', "system-ui", "sans-serif"],
        display: ['"Space Grotesk"', '"Inter"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
    },
  },
  plugins: [],
};
