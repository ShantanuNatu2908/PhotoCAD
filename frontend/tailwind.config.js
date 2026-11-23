/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cad: {
          dark: '#0f141c',
          card: '#161d28',
          border: '#242f40',
          accent: '#00f0ff',
          neon: '#39ff14',
          warning: '#ffb703',
          danger: '#ff0055'
        }
      }
    },
  },
  plugins: [],
}
