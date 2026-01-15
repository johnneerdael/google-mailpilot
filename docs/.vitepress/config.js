import { defineConfig } from "vitepress";

export default defineConfig({
  title: "Google MailPilot",
  description: "AI-native Gmail command center documentation",
  base: "/",
  srcDir: ".",
  cleanUrls: "without-subfolders",
  appearance: true,
  themeConfig: {
    logo: "/hero.jpeg",
    siteTitle: "MailPilot Docs",
    nav: [
      { text: "Getting Started", link: "/getting-started" },
      { text: "Guide", link: "/guide/" },
      { text: "Tools", link: "/tools/" },
      { text: "Embeddings", link: "/embeddings/" },
      { text: "Web Portal", link: "/webserver/" },
      { text: "Roadmap", link: "/roadmap/" },
      { text: "Platform", link: "/platform/platform-ops" },
      { text: "Releases", link: "/releases/v5-0-0" },
    ],
    socialLinks: [
      { icon: "github", link: "https://github.com/johnneerdael/google-mailpilot" },
    ],
    footer: {
      message: "Released under MIT",
      copyright: "© 2024-present John Neerdael"
    },
    sidebar: {
      "/guide/": [
        {
          text: "Guide",
          items: [
            { text: "Overview", link: "/guide/" },
            { text: "Architecture", link: "/guide/architecture" },
            { text: "Configuration", link: "/guide/configuration" },
            { text: "Docker", link: "/guide/docker" },
            { text: "Security", link: "/guide/security" },
            { text: "Semantic Search", link: "/guide/semantic-search" },
            { text: "Use Cases", link: "/guide/use-cases" },
            { text: "Agents", link: "/guide/agents" },
            { text: "Mutation Journal", link: "/guide/mutation-journal" },
            { text: "OpenCode Setup", link: "/guide/opencode" },
            { text: "Web UI", link: "/guide/web-ui" },
            { text: "Clients", link: "/guide/clients" },
            { text: "Threading", link: "/guide/threading" },
          ]
        }
      ],
      "/tools/": [
        {
          text: "Tools",
          items: [
            { text: "Overview", link: "/tools/" },
            { text: "Email Tools", link: "/tools/email" },
            { text: "Calendar Tools", link: "/tools/calendar" },
            { text: "Intelligence Tools", link: "/tools/intelligence" },
          ]
        }
      ],
      "/embeddings/": [
        {
          text: "Embeddings",
          items: [
            { text: "Overview", link: "/embeddings/" },
            { text: "Architecture", link: "/embeddings/architecture" },
            { text: "Dimensions", link: "/embeddings/dimensions" },
            { text: "Database Schema", link: "/embeddings/database-schema" },
            { text: "Configuration", link: "/embeddings/config-reference" },
            { text: "Providers", link: "/embeddings/providers" },
            { text: "Quick Start", link: "/embeddings/quick-start" },
            { text: "Performance", link: "/embeddings/performance" },
            { text: "Cost", link: "/embeddings/cost" },
            { text: "Troubleshooting", link: "/embeddings/troubleshooting" },
          ]
        }
      ],
      "/webserver/": [
        {
          text: "Web Portal",
          items: [
            { text: "Index", link: "/webserver/" },
            { text: "Web UI", link: "/webserver/web-ui" },
            { text: "API", link: "/webserver/api" },
            { text: "Configuration", link: "/webserver/configuration" },
            { text: "Security", link: "/webserver/security" },
            { text: "Troubleshooting", link: "/webserver/troubleshooting" },
          ]
        }
      ],
      "/roadmap/": [
        {
          text: "Roadmap",
          items: [
            { text: "Index", link: "/roadmap/" },
            { text: "Gap Analysis", link: "/roadmap/gap-analysis" },
            { text: "Recommendations", link: "/roadmap/recommendations" },
            { text: "Appendix", link: "/roadmap/appendix-routes" }
          ]
        }
      ],
      "/platform/": [
        {
          text: "Platform Operations",
          items: [
            { text: "Platform Ops Guide", link: "/platform/platform-ops" }
          ]
        }
      ],
      "/releases/": [
        {
          text: "Releases",
          items: [{ text: "v5.0.0", link: "/releases/v5-0-0" }]
        }
      ]
    }
  }
});