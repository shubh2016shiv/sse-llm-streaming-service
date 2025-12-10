/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'bg-dark': '#0F172A',
        'bg-card': '#1E293B',
        'bg-tertiary': '#334155',
        'text-primary': '#F1F5F9',
        'text-secondary': '#94A3B8',
        'text-muted': '#64748B',
        'accent-primary': '#3B82F6',
        'accent-secondary': '#8B5CF6',
        'success': '#10B981',
        'warning': '#F59E0B',
        'danger': '#EF4444',
        'border': '#334155',
        'border-hover': '#475569',
      },
      boxShadow: {
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2)',
        'card-hover': '0 8px 12px -2px rgba(0, 0, 0, 0.4), 0 4px 6px -1px rgba(0, 0, 0, 0.3)',
      },
    },
  },
  plugins: [],
}

