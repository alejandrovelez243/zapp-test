import type { NextConfig } from "next";

// Fallback to localhost:8000 so local dev and CI builds succeed without a real
// backend URL.  Override with NEXT_PUBLIC_API_URL in your .env.local (or Vercel
// environment) to point at the Railway-deployed FastAPI service.
const apiBase =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        // Proxy /api/:path* → FastAPI  (same-origin in the browser → no CORS needed)
        source: "/api/:path*",
        destination: `${apiBase}/:path*`,
      },
    ];
  },
};

export default nextConfig;
