'use client'

import { ThemeProvider } from 'next-themes'
import { Toaster } from 'sonner'

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      {children}
      <Toaster
        position="bottom-center"
        toastOptions={{
          classNames: {
            toast: '!bg-surface !text-ink !border-line',
            description: '!text-muted',
          },
        }}
      />
    </ThemeProvider>
  )
}
