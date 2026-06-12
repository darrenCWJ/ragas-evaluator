/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // "Instrument" theme — graphite engineering-lab surfaces, cyan signal
      // accent. Values live as RGB-triple CSS variables in index.css so the
      // light theme can override them at runtime (html[data-theme='light'])
      // while every /opacity utility keeps working.
      colors: {
        deep: 'rgb(var(--color-deep) / <alpha-value>)',
        base: 'rgb(var(--color-base) / <alpha-value>)',
        card: 'rgb(var(--color-card) / <alpha-value>)',
        elevated: 'rgb(var(--color-elevated) / <alpha-value>)',
        input: 'rgb(var(--color-input) / <alpha-value>)',
        border: 'rgb(var(--color-border) / <alpha-value>)',
        'border-focus': 'rgb(var(--color-accent) / <alpha-value>)',
        'text-primary': 'rgb(var(--color-text-primary) / <alpha-value>)',
        'text-secondary': 'rgb(var(--color-text-secondary) / <alpha-value>)',
        'text-muted': 'rgb(var(--color-text-muted) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        'accent-glow': 'rgb(var(--color-accent) / 0.14)',
        'score-high': 'rgb(var(--color-score-high) / <alpha-value>)',
        'score-mid': 'rgb(var(--color-score-mid) / <alpha-value>)',
        'score-low': 'rgb(var(--color-score-low) / <alpha-value>)',
        'delta-pos': 'rgb(var(--color-score-high) / <alpha-value>)',
        'delta-neg': 'rgb(var(--color-score-low) / <alpha-value>)',
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }], // 10px
        micro: ['0.6875rem', { lineHeight: '1rem' }], // 11px
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', '"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
};
