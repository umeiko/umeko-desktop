import { defineConfig, type DefaultTheme } from 'vitepress'
import { readFileSync } from 'node:fs'

const base = process.env.DOCS_BASE || '/umeko-desktop/'
if (!/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(base)) {
  throw new Error('DOCS_BASE must be / or a slash-delimited path such as /umeko-desktop/.')
}

function sidebar(en = false): DefaultTheme.SidebarItem[] {
  const prefix = en ? '/en' : ''
  const item = (path: string, zh: string, english: string) => ({ text: en ? english : zh, link: `${prefix}/${path}` })
  return [
    { text: en ? 'Get started' : '开始使用', items: [
      item('start/quick-start', '五分钟上手', 'Quick start'),
      item('start/install', '安装与更新', 'Install & update')
    ] },
    { text: en ? 'Work with Umeko' : '和 Umeko 一起工作', items: [
      item('guide/conversations', '项目、聊天与任务状态', 'Projects & conversations'),
      item('guide/providers', '账号与模型供应商', 'Accounts & models'),
      item('guide/subagents', '委派子智能体', 'Delegate to subagents'),
      item('guide/artifacts', '文件、网页与产物预览', 'Files & artifact previews'),
      item('guide/skills', 'Skills、扩展与 MCP', 'Skills, extensions & MCP'),
      item('guide/widgets', 'Widgets 与桌面宠物', 'Widgets & desktop pets'),
      item('guide/appearance', '主题、角色与外观', 'Themes & characters'),
      item('guide/api-proxy', 'API 代理服务', 'API proxy')
    ] },
    { text: en ? 'Help & reference' : '技巧与参考', items: [
      item('guide/tips', '可以这样问我', 'Things to try'),
      item('faq', '常见问题', 'FAQ'),
      item('troubleshooting', '故障排查与反馈', 'Troubleshooting'),
      item('reference/development', '开发与 SDK', 'Development & SDKs'),
      item('reference/contributing', '完善这份文档', 'Contribute to the docs')
    ] }
  ]
}

export default defineConfig({
  title: 'Umeko Desktop',
  description: 'Umeko Desktop 使用文档：安装、模型、子智能体、Skills、Widgets 与常见问题。',
  base,
  srcExclude: ['README.md', 'node_modules/**'],
  cleanUrls: false,
  head: [['link', { rel: 'icon', type: 'image/png', href: `${base}logo.png` }]],
  markdown: {
    theme: { light: 'github-light', dark: 'github-dark' },
    config(md) {
      const render = md.renderer.rules.image!
      md.renderer.rules.image = (tokens, index, options, env, self) => {
        tokens[index].attrSet('loading', 'lazy')
        tokens[index].attrSet('decoding', 'async')
        const src = tokens[index].attrGet('src') || ''
        if (/^\/images\/[a-z-]+\.png$/.test(src)) {
          const png = readFileSync(new URL(`../public${src}`, import.meta.url))
          tokens[index].attrSet('width', String(png.readUInt32BE(16)))
          tokens[index].attrSet('height', String(png.readUInt32BE(20)))
        }
        return render(tokens, index, options, env, self)
      }
    }
  },
  locales: {
    root: {
      label: '简体中文', lang: 'zh-Hans',
      themeConfig: {
        nav: [
          { text: '使用指南', link: '/start/quick-start' },
          { text: '常见问题', link: '/faq' },
          { text: '开发者', link: '/reference/development' }
        ],
        sidebar: sidebar(),
        outline: { label: '本页内容', level: [2, 3] },
        docFooter: { prev: '上一页', next: '下一页' },
        editLink: { pattern: 'https://github.com/umeiko/umeko-desktop/edit/main/docs-site/:path', text: '在 GitHub 上完善此页' },
        returnToTopLabel: '回到顶部', sidebarMenuLabel: '目录', darkModeSwitchLabel: '外观',
        lightModeSwitchTitle: '切换为浅色', darkModeSwitchTitle: '切换为深色',
        langMenuLabel: '切换语言', skipToContentLabel: '跳转到正文',
        notFound: { title: '没有找到这一页', quote: '也许页面搬家了。试试搜索，或者回到首页继续。', linkText: '回到首页', linkLabel: '回到文档首页' },
        footer: { message: '独立同人项目，与角色权利方无关联。', copyright: '由 Umeko 社区维护 · 文档与源码一起演进' }
      }
    },
    en: {
      label: 'English', lang: 'en', description: 'Learn Umeko Desktop: installation, models, subagents, Skills, Widgets and troubleshooting.',
      themeConfig: {
        nav: [
          { text: 'Guide', link: '/en/start/quick-start' },
          { text: 'FAQ', link: '/en/faq' },
          { text: 'Developers', link: '/en/reference/development' }
        ],
        sidebar: sidebar(true), outline: { label: 'On this page', level: [2, 3] },
        editLink: { pattern: 'https://github.com/umeiko/umeko-desktop/edit/main/docs-site/:path', text: 'Improve this page on GitHub' },
        footer: { message: 'An independent fan project, unaffiliated with the character rights holders.', copyright: 'Maintained by the Umeko community · Docs evolve with the code' }
      }
    }
  },
  themeConfig: {
    logo: { src: '/logo.png', alt: '' },
    siteTitle: 'Umeko Docs',
    socialLinks: [{ icon: 'github', link: 'https://github.com/umeiko/umeko-desktop' }],
    externalLinkIcon: true,
    search: {
      provider: 'local',
      options: {
        miniSearch: {
          options: {
            // Also segment Chinese words: whitespace tokenization cannot search Chinese prose.
            tokenize: (text: string) => Array.from(
              new Intl.Segmenter('zh', { granularity: 'word' }).segment(text),
              segment => segment.isWordLike ? segment.segment.toLowerCase() : ''
            ).filter(Boolean)
          }
        },
        locales: {
          root: {
            translations: {
              button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
              modal: {
                noResultsText: '没有找到相关内容', resetButtonTitle: '清空搜索',
                backButtonTitle: '关闭搜索', displayDetails: '显示详情',
                footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' }
              }
            }
          }
        }
      }
    }
  }
})
