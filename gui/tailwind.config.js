/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: '#080c18', light: '#f0f4f8' },
        surface: { DEFAULT: '#0f1629', light: '#ffffff', 2: '#1a2340', light2: '#e8edf4' },
        border: { DEFAULT: '#1e3a5f', light: '#d0d7e2' },
        accent: { DEFAULT: '#60a5fa', 2: '#818cf8' },
        green: '#34d399',
        red: '#f87171',
        yellow: '#fbbf24',
        purple: '#c084fc',
        cyan: '#22d3ee',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['SF Mono', 'Menlo', 'Consolas', 'monospace'],
      },
      animation: {
        'panel-in': 'panelIn 0.25s cubic-bezier(0.4,0,0.2,1)',
        'msg-in': 'msgIn 0.25s cubic-bezier(0.4,0,0.2,1)',
        'overlay-in': 'overlayIn 0.25s cubic-bezier(0.4,0,0.2,1)',
        'bubble-in': 'bubbleIn 0.25s cubic-bezier(0.4,0,0.2,1)',
        'spin-slow': 'spin 0.6s linear infinite',
        'pulse-soft': 'pulse 1.5s ease-in-out infinite',
        'ticker': 'tickerScroll 120s linear infinite',
      },
      keyframes: {
        panelIn: { from: { opacity: 0, transform: 'translateY(8px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
        msgIn: { from: { opacity: 0, transform: 'translateY(8px) scale(0.97)' }, to: { opacity: 1, transform: 'translateY(0) scale(1)' } },
        overlayIn: { from: { opacity: 0, transform: 'translateY(12px) scale(0.97)' }, to: { opacity: 1, transform: 'translateY(0) scale(1)' } },
        bubbleIn: { from: { opacity: 0, transform: 'scale(0.85)' }, to: { opacity: 1, transform: 'scale(1)' } },
        tickerScroll: { '0%': { transform: 'translateX(0)' }, '100%': { transform: 'translateX(-50%)' } },
      },
    },
  },
  plugins: [],
}
