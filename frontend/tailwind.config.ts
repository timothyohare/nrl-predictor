import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        nrl: { blue: "#003087", gold: "#FFD700" },
      },
    },
  },
  plugins: [],
};

export default config;
