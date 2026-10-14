import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
    output: 'standalone',
    agentRules: false,
    devIndicators: false,
    reactCompiler: true,
};

export default nextConfig;
