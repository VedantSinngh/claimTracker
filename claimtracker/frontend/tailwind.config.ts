import type { Config } from "tailwindcss";

/**
 * Design tokens live here rather than as ad-hoc classes so the status colours
 * used by badges, charts and the reviewer queue stay consistent across pages.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e5ff",
          500: "#2f6fed",
          600: "#2259cc",
          700: "#1b46a0",
        },
        // One colour per claim status, reused by StatusBadge and the charts.
        status: {
          pending: "#92700c",
          processing: "#1b6a8f",
          accepted: "#15713f",
          rejected: "#a3242a",
          review: "#8a4b12",
        },
      },
    },
  },
  plugins: [],
};

export default config;
