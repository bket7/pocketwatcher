/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'pw-dark': '#0f1419',
        'pw-card': '#1a1f26',
        'pw-border': '#2f3640',
        'pw-green': '#00c853',
        'pw-red': '#ff5252',
        'pw-yellow': '#ffc107',
        'pw-blue': '#2196f3',
      },
    },
  },
  plugins: [],
}
