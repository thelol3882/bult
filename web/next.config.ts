import type { NextConfig } from 'next';

// Rewrites are baked into routes-manifest.json at `next build`, so in a production
// image API_INTERNAL_URL is a build-time value. `next dev` reads it at server start.
const apiUrl = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';

const nextConfig: NextConfig = {
    output: 'standalone',
    agentRules: false,
    devIndicators: false,
    reactCompiler: true,
    async rewrites() {
        return [{ source: '/api/:path*', destination: `${apiUrl}/:path*` }];
    },
};

export default nextConfig;
