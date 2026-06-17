/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ghaf: {
          50: "#eef4ff",
          100: "#dbe7ff",
          200: "#bcd2ff",
          300: "#8eb4ff",
          400: "#5a8bff",
          500: "#3563ff",
          600: "#1f43f0",
          700: "#1a34c2",
          800: "#1b2f9a",
          900: "#1c2c79",
        },
      },
    },
  },
  plugins: [],
};
