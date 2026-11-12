import '../styles/globals.css'

import type { Metadata, Viewport } from 'next'
import { Geist, Geist_Mono, Source_Serif_4 } from 'next/font/google'

import { Providers } from '@/components/Providers'

const sans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] })
const mono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] })
const serif = Source_Serif_4({ variable: '--font-serif', subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Lumina · Compliance assistant',
  description: 'Ask questions about your policy documents and get answers cited to the page.',
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f7f5f0' },
    { media: '(prefers-color-scheme: dark)', color: '#141311' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${sans.variable} ${mono.variable} ${serif.variable}`}
    >
      <body className="font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
