import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "Gmail Secretary MCP",
  description: "AI-native secretary for Gmail and Google Calendar via MCP",
  base: process.env.VITEPRESS_BASE || "/gmail-secretary-mcp/",
  
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    logo: '/logo.svg',
    
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Getting Started', link: '/getting-started' },
      { text: 'Guide', link: '/guide/' },
      { text: 'Web Server', link: '/webserver/' },
      { text: 'Embeddings', link: '/embeddings/' },
      { text: 'MCP Tools', link: '/tools/' },
      { text: 'Roadmap', link: '/roadmap/' },
      {
        text: 'v4.6.0',
        items: [
          { text: 'Changelog', link: 'https://github.com/johnneerdael/gmail-secretary-mcp/releases' },
          { text: 'Contributing', link: 'https://github.com/johnneerdael/gmail-workspace-mcp' }
        ]
      }
    ],
    sidebar: {
      '/guide/': [
        {
          text: 'Guide',
          items: [
            { text: 'Getting Started', link: '/guide/getting-started' },
            { text: 'Configuration', link: '/guide/configuration' },
            { text: 'Calendar Integration', link: '/guide/calendar' },
            { text: 'Security', link: '/guide/security' },
            { text: 'OAuth Workaround', link: '/guide/oauth_workaround' },
            { text: 'Docker Deployment', link: '/guide/docker' },
            { text: 'Web UI', link: '/guide/web-ui' },
            { text: 'Semantic Search', link: '/guide/semantic-search' },
            { text: 'Email Threading', link: '/guide/threading' },
            { text: 'Agent System', link: '/guide/agents' },
            { text: 'Use Cases', link: '/guide/use-cases' },
            { text: 'OpenCode Integration', link: '/guide/opencode' },
            { text: 'Mutation Journal', link: '/guide/mutation-journal' },
            { text: 'Server Architecture', link: '/guide/architecture' },
          ]
        }
      ],
    
      '/webserver/': [
        {
          text: 'Web Server',
          items: [
            { text: 'Overview', link: '/webserver/' },
            { text: 'Web UI basics', link: '/webserver/web-ui' },
            { text: 'Mobile support', link: '/webserver/mobile' },
          ]
        },
        {
          text: 'Features',
          items: [
            { text: 'Search', link: '/webserver/search' },
            { text: 'AI chat', link: '/webserver/chat' },
            { text: 'Settings & notifications', link: '/webserver/settings' },
          ]
        },
        {
          text: 'Reference',
          items: [
            { text: 'Configuration', link: '/webserver/configuration' },
            { text: 'API endpoints', link: '/webserver/api' },
            { text: 'Security', link: '/webserver/security' },
            { text: 'Customization', link: '/webserver/customization' },
            { text: 'Troubleshooting', link: '/webserver/troubleshooting' },
            { text: 'Embeddings', link: '/webserver/embeddings' }
          ]
        }
      ],
    
      '/embeddings/': [
        {
          text: 'Embeddings',
          items: [
            { text: 'Overview', link: '/embeddings/' },
            { text: 'How it works', link: '/embeddings/overview' },
            { text: 'Architecture', link: '/embeddings/architecture' },
            { text: 'Dimensions & storage', link: '/embeddings/dimensions' },
            { text: 'Quick start', link: '/embeddings/quick-start' },
            { text: 'Providers', link: '/embeddings/providers' },
            { text: 'Migration', link: '/embeddings/migration' },
            { text: 'Configuration reference', link: '/embeddings/config-reference' },
            { text: 'Database schema', link: '/embeddings/database-schema' },
            { text: 'Performance tuning', link: '/embeddings/performance' },
            { text: 'MCP tools', link: '/embeddings/mcp-tools' },
            { text: 'Web UI integration', link: '/embeddings/web-ui' },
            { text: 'Troubleshooting', link: '/embeddings/troubleshooting' },
            { text: 'Cost estimation', link: '/embeddings/cost' }
          ]
        }
      ],
    
      '/roadmap/': [
        {
          text: 'Roadmap',
          items: [
            { text: 'Overview', link: '/roadmap/' },
            { text: 'Codebase structure', link: '/roadmap/codebase-structure' },
            { text: 'Feature audit — Email & search', link: '/roadmap/feature-audit-email' },
            { text: 'Feature audit — Calendar', link: '/roadmap/feature-audit-calendar' },
            { text: 'Feature audit — UX & security', link: '/roadmap/feature-audit-ux' },
            { text: 'Priority gap analysis', link: '/roadmap/gap-analysis' },
            { text: 'Recommendations', link: '/roadmap/recommendations' },
            { text: 'Appendix — by route', link: '/roadmap/appendix-routes' }
          ]
        }
      ]
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/johnneerdael/gmail-secretary-mcp' }
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2024-present John Neerdael'
    },

    search: {
      provider: 'local'
    },

    editLink: {
      pattern: 'https://github.com/johnneerdael/gmail-secretary-mcp/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    }
  }
})
