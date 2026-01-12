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
              { text: 'Docker Deployment', link: '/guide/docker' },
              { text: 'Web UI', link: '/guide/web-ui' },
              { text: 'Semantic Search', link: '/guide/semantic-search' },
              { text: 'Email Threading', link: '/guide/threading' },
              { text: 'Agent System', link: '/guide/agents' },
              { text: 'Use Cases', link: '/guide/use-cases' },
              { text: 'OpenCode Integration', link: '/guide/opencode' },
              { text: 'Mutation Journal', link: '/guide/mutation-journal' }
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
