import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: {
      modules: {
        // Retorna o nome da classe como-está para testes (ex: styles.badgeAmbar => 'badgeAmbar')
        classNameStrategy: 'non-scoped',
      },
    },
  },
});
