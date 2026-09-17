import api from '@/utils/axios'
import { ref } from 'vue'
import {
  DEFAULT_BRANDING,
  DEFAULT_REPO_URL,
  type PublicBranding,
} from '@/constants/branding'

const BRANDING_CACHE_KEY = 'nanzi_public_branding'

function readCachedBranding(): PublicBranding | null {
  if (typeof localStorage === 'undefined') return null
  try {
    const raw = localStorage.getItem(BRANDING_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PublicBranding>
    if (!parsed || typeof parsed !== 'object') return null
    const productName = typeof parsed.product_name === 'string' ? parsed.product_name.trim() : ''
    if (!productName) return null
    return { ...DEFAULT_BRANDING, ...parsed, product_name: productName }
  } catch {
    return null
  }
}

function writeCachedBranding(value: PublicBranding) {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(BRANDING_CACHE_KEY, JSON.stringify(value))
  } catch {
    // 配额或隐私模式写失败时忽略，不影响当次展示
  }
}

const branding = ref<PublicBranding>(
  readCachedBranding() ?? { ...DEFAULT_BRANDING, product_name: '' },
)
let loadPromise: Promise<PublicBranding> | null = null

function applyFavicon(iconUrl: string) {
  if (typeof document === 'undefined') return
  const href = iconUrl || DEFAULT_BRANDING.icon_url
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.href = href
}

export function applyDocumentTitle(pageTitle?: string) {
  if (typeof document === 'undefined') return
  const name = branding.value.product_name || DEFAULT_BRANDING.product_name
  document.title = pageTitle ? `${pageTitle} - ${name}` : name
}

export function resolveRepoUrl(): string {
  if (branding.value.hide_version_link) return ''
  return DEFAULT_REPO_URL
}

function applyCachedChrome() {
  applyFavicon(branding.value.icon_url)
  applyDocumentTitle()
}

export async function loadBranding(force = false): Promise<PublicBranding> {
  if (!force && loadPromise) return loadPromise

  loadPromise = (async () => {
    try {
      const res = await api.get('/api/portal/auth/branding')
      const data = res.data?.data ?? res.data
      branding.value = { ...DEFAULT_BRANDING, ...data }
      writeCachedBranding(branding.value)
    } catch {
      if (!branding.value.product_name) {
        branding.value = { ...DEFAULT_BRANDING }
      }
    }
    applyCachedChrome()
    return branding.value
  })()

  return loadPromise
}

applyCachedChrome()
if (typeof window !== 'undefined') {
  void loadBranding()
}

export function useBranding() {
  return {
    branding,
    loadBranding,
    applyDocumentTitle,
    applyFavicon,
    resolveRepoUrl,
  }
}
