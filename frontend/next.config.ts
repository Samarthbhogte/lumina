import type { NextConfig } from 'next'

const dev = process.env.NODE_ENV !== 'production'

// Answers are model output built from uploaded documents, so treat them as untrusted:
// no remote images (a classic exfiltration channel), no plugins, no framing.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ''}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self'${dev ? ' ws:' : ''}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ')

// The browser talks only to this origin; /api/* is proxied to FastAPI. Same-origin keeps
// session cookies on every request (including SSE and PDF links) and removes CORS.
const apiInternal = (process.env.LUMINA_API_INTERNAL_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')

const nextConfig: NextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  experimental: {
    // Answers stream for a while and uploads embed before replying: the 30 s default is too short.
    proxyTimeout: 300_000,
    proxyClientMaxBodySize: '260mb',
  },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${apiInternal}/api/:path*` }]
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Content-Security-Policy', value: csp },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ]
  },
}

export default nextConfig
