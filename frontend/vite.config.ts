import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: { name: "Planner", short_name: "Planner", display: "standalone", theme_color: "#111111", background_color: "#ffffff" },
    }),
  ],
});
