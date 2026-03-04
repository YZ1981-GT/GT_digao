/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#f5f3f7',
          100: '#ebe6ef',
          200: '#d4cce0',
          300: '#b8a8cc',
          400: '#9b7fb8',
          500: '#7A4FD6',
          600: '#4E2D7F',
          700: '#3A1E6D',
          800: '#2d1754',
          900: '#1f1039',
        },
        accent: {
          teal: '#00B4B3',
          coral: '#F56B45',
          yellow: '#FFC23D',
        },
        gt: {
          purple: '#4E2D7F',
          'purple-dark': '#3A1E6D',
          'purple-light': '#7A4FD6',
        }
      }
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
}