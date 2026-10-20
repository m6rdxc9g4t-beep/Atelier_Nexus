import type { NextConfig } from "next";

/**
 * NEXUS_EXPORT=1 : interface compilée en fichiers statiques (frontend/out), servie par le
 * backend dans l'application de bureau macOS (scripts/macos/build_app.sh).
 * Sinon : image Docker minimale (.next/standalone + server.js).
 */
const exportStatic = process.env.NEXUS_EXPORT === "1";

const nextConfig: NextConfig = {
  output: exportStatic ? "export" : "standalone",
  // Rendu partiel (PPR) : incompatible avec l'export statique
  cacheComponents: !exportStatic,
  partialPrefetching: !exportStatic,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
