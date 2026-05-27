import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#f0f2f5",
        surface: "#fafbfc",
        "surface-elevated": "#ffffff",
        "surface-2": "#e8ecf1",
        border: "#d4dbe4",
        foreground: "#152033",
        muted: "#5a6578",
        subtle: "#8b95a5",
        accent: "#1a6b5c",
        "accent-hover": "#145549",
        "accent-soft": "#e3f0ec",
        "accent-muted": "#b8d9d0",
        ok: "#166534",
        "ok-soft": "#ecfdf5",
        warn: "#b45309",
        "warn-soft": "#fffbeb",
        danger: "#be123c",
        "danger-soft": "#fff1f2",
        ink: "#152033",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "-apple-system", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      maxWidth: {
        prose: "40rem",
        content: "72rem",
      },
      borderRadius: {
        media: "0.75rem",
      },
    },
  },
  plugins: [],
};

export default config;
