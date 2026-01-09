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
      { text: 'Architecture', link: '/architecture' },
      { text: 'MCP Tools', link: '/api/' },
      {
        text: 'v4.2.1',
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
            { text: 'Introduction', link: '/guide/' },
            { text: 'Configuration', link: '/guide/configuration' },
            { text: 'Security', link: '/guide/security' },
            { text: 'OAuth Workaround', link: '/guide/oauth_workaround' },
            { text: 'Docker Deployment', link: '/guide/docker' },
            { text: 'Semantic Search', link: '/guide/semantic-search' },
            { text: 'Threading', link: '/guide/threading' },
            { text: 'Agent Patterns', link: '/guide/agents' },
            { text: 'Use Cases', link: '/guide/use-cases' },
            { text: 'OpenCode Integration', link: '/guide/opencode' }
          ]
        }
      ],
      '/api/': [
        {
          text: 'MCP Tools Reference',
          items: [
            { text: 'Overview', link: '/api/' },
            { text: 'Email Tools', link: '/api/email' },
            { text: 'Calendar Tools', link: '/api/calendar' },
            { text: 'Intelligence Tools', link: '/api/intelligence' }
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
