import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: false,
      workbox: { cleanupOutdatedCaches: true, clientsClaim: true, skipWaiting: true, navigateFallbackDenylist: [/^\/api\//] },
      manifest: {
        name: "CIS Planner", short_name: "CIS Planner", display: "standalone", theme_color: "#e9e3d5", background_color: "#f3efe6",
        icons: [{ src: "/icon-192.png", sizes: "192x192", type: "image/png" }, { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" }],
      },
    }),
  ],
});
