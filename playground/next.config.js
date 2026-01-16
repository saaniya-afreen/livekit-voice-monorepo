const createNextPluginPreval = require("next-plugin-preval/config");
const withNextPluginPreval = createNextPluginPreval();

/** @type {import('next').NextConfig} */
// IMPORTANT:
// - Local dev uses API routes (e.g. `/api/token`) for token generation.
// - Next.js static export (`output: "export"`) cannot be used with API routes.
//
// So: only enable static export when explicitly requested (e.g. CI deploy).
const isStaticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: false,
  ...(isStaticExport
    ? {
        output: "export",
        trailingSlash: true,
        images: {
          unoptimized: true,
        },
      }
    : {}),
};

module.exports = withNextPluginPreval(nextConfig);
