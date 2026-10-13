export default defineNuxtConfig({
  compatibilityDate: '2026-09-01',

  // Single-page mode on purpose. This is an authenticated dashboard: server-rendering it would
  // only ever emit a signed-out shell plus a hydration pass, and prerendering would fight the
  // static host's catch-all rewrite. The API does the interesting work.
  ssr: false,

  devtools: { enabled: false },
  css: ['~/assets/css/main.css'],

  // Declared through Nuxt's own PostCSS option rather than a root postcss.config.js: Nuxt owns
  // the CSS pipeline (Vite does not pick the config file up here), and this is the supported
  // entry point for PostCSS plugins.
  postcss: {
    plugins: {
      '@tailwindcss/postcss': {},
    },
  },

  runtimeConfig: {
    public: {
      // Baked in at build time — a static bundle has no runtime environment to read.
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000',
    },
  },

  app: {
    head: {
      title: 'Agent Workbench',
      htmlAttrs: { lang: 'zh-CN' },
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        {
          name: 'description',
          content: '可观测、可评测、可续跑的 Agent 运行时',
        },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap',
        },
      ],
    },
  },

  nitro: {
    preset: 'static',
  },

  typescript: {
    strict: true,
  },
})
