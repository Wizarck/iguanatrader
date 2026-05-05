import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

/**
 * Vite config — slice W1 (`dashboard-svelte-skeleton`).
 *
 * Tailwind 4.x uses the native Vite plugin (`@tailwindcss/vite`); no
 * `tailwind.config.ts` or `postcss.config.cjs` is needed. The token cascade
 * lives in `src/app.css` under `:root[data-theme='dark']` (per design D10).
 */
export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  test: {
    include: ['tests/**/*.test.ts'],
    globals: true,
    environment: 'node'
  }
});
