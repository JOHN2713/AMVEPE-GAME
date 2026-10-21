/** @type {import('tailwindcss').Config} */
// Los valores replican los tokens de :root en src/input.css (se declaran en hex para que Tailwind
// pueda aplicar modificadores de opacidad como bg-primary/20).
module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#1D9A90", hover: "#167F77", soft: "#E3F3F1" },
        bg: "#F2F4F4",
        ink: "#030712",
        surface: "#FFFFFF",
        line: "#D8E0E0",
        correct: { DEFAULT: "#15803D", soft: "#DCFCE7" },
        incorrect: { DEFAULT: "#B91C1C", soft: "#FEE2E2" },
        focus: "#0F766E",
        muted: "#4B5563",
      },
      fontFamily: {
        sans: ["Montserrat", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(3 7 18 / 0.06), 0 8px 24px rgb(3 7 18 / 0.06)",
      },
    },
  },
  plugins: [],
};
