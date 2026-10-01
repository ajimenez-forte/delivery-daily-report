import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // forbidden() responde con 403 real en el servidor.
  experimental: { authInterrupts: true },
  poweredByHeader: false,
};

export default nextConfig;
