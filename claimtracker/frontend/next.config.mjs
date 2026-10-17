/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output keeps the production image small (see Dockerfile).
  output: "standalone",
};

export default nextConfig;
