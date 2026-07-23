/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  eslint: {
    ignoreDuringBuilds: true,
  },
  images: {
    // Custom pass-through loader (see lib/image-loader.ts) instead of
    // remotePatterns: thumbnail URLs are presigned and already
    // backend-resized, so there's no S3-provider hostname to hardcode here.
    loader: 'custom',
    loaderFile: './lib/image-loader.ts',
  },
}

module.exports = nextConfig
