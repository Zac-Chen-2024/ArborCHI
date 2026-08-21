import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    // happy-dom rather than jsdom: the logger only needs localStorage,
    // window events and Blob, and happy-dom starts in a fraction of the time.
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    restoreMocks: true,
  },
})
