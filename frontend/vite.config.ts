import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: { name: "CIS Planner", short_name: "CIS Planner", display: "standalone", theme_color: "#e9e3d5", background_color: "#f3efe6" },
    }),
  ],
});
