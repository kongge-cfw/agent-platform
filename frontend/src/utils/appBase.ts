declare global {
  interface Window {
    __APP_BASE_PATH__?: string
  }
}

const BACKEND_PAGE_RE = /^\/(oauth\/authorize|docs|redoc|openapi\.json)(\/|\?|$)/

export function normalizeBase(raw: string | undefined | null): string {
  const text = String(raw || '').trim()
  if (!text || text === '/') return ''
  return `/${text.replace(/^\/+|\/+$/g, '')}`
}

export function getAppBasePath(): string {
  if (typeof window === 'undefined') return ''
  return normalizeBase(window.__APP_BASE_PATH__)
}

export function routerBase(): string {
  const base = getAppBasePath()
  return base ? `${base}/` : '/'
}

export function withAppBase(path: string): string {
  if (!path) return getAppBasePath() || '/'
  if (path.startsWith('blob:') || path.startsWith('data:') || path.startsWith('ws:') || path.startsWith('wss:')) {
    return path
  }
  if (/^https?:\/\//i.test(path)) {
    try {
      const url = new URL(path)
      if (typeof window === 'undefined' || url.origin !== window.location.origin) {
        return path
      }
      url.pathname = prefixPathname(url.pathname)
      return url.toString()
    } catch {
      return path
    }
  }

  const hashIdx = path.indexOf('#')
  const hash = hashIdx >= 0 ? path.slice(hashIdx) : ''
  const noHash = hashIdx >= 0 ? path.slice(0, hashIdx) : path
  const queryIdx = noHash.indexOf('?')
  const search = queryIdx >= 0 ? noHash.slice(queryIdx) : ''
  const pathname = queryIdx >= 0 ? noHash.slice(0, queryIdx) : noHash
  if (!pathname.startsWith('/')) {
    return `${pathname}${search}${hash}`
  }
  return `${prefixPathname(pathname)}${search}${hash}`
}

function prefixPathname(pathname: string): string {
  const base = getAppBasePath()
  if (!base || pathname === base || pathname.startsWith(`${base}/`)) {
    return pathname
  }
  return `${base}${pathname}`
}

export function stripAppBase(path: string): string {
  const hashIdx = path.indexOf('#')
  const hash = hashIdx >= 0 ? path.slice(hashIdx) : ''
  const noHash = hashIdx >= 0 ? path.slice(0, hashIdx) : path
  const queryIdx = noHash.indexOf('?')
  const search = queryIdx >= 0 ? noHash.slice(queryIdx) : ''
  const pathname = queryIdx >= 0 ? noHash.slice(0, queryIdx) : noHash
  const base = getAppBasePath()
  let next = pathname
  if (base && (next === base || next.startsWith(`${base}/`))) {
    next = next.slice(base.length) || '/'
  }
  if (!next.startsWith('/')) next = `/${next}`
  return `${next}${search}${hash}`
}

export function appPathStartsWith(pathname: string, prefix: string): boolean {
  const path = stripAppBase(pathname).split('?')[0]
  const target = prefix.startsWith('/') ? prefix : `/${prefix}`
  if (target === '/') return path === '/'
  return path === target || path.startsWith(`${target}/`) || (target.endsWith('/') && path.startsWith(target))
}

function pathnameOf(url: string): string {
  const raw = String(url || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) {
    try {
      return new URL(raw).pathname
    } catch {
      return raw.split('#')[0].split('?')[0]
    }
  }
  return raw.split('#')[0].split('?')[0]
}

export function isPlatformRoutedUrl(url: string): boolean {
  const path = pathnameOf(url)
  return appPathStartsWith(path, '/api') || appPathStartsWith(path, '/static') || appPathStartsWith(path, '/assets')
}

export function appLoginPath(): string {
  return withAppBase('/login')
}

export function clearClientAuth(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem('api_key')
  localStorage.removeItem('user_info')
  localStorage.removeItem('admin_token')
  localStorage.removeItem('yovole_token')
  const cookiePath = getAppBasePath() || '/'
  document.cookie = `admin_token=; path=${cookiePath}; max-age=0; samesite=lax`
}

export function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  if (window.location.pathname !== appLoginPath()) {
    window.location.href = appLoginPath()
  }
}

export function isEmbedLocation(pathname = typeof window === 'undefined' ? '' : window.location.pathname): boolean {
  return appPathStartsWith(pathname, '/embed') || pathname.includes('EmbedChat')
}

export function isBackendNextPath(path: string): boolean {
  return BACKEND_PAGE_RE.test(stripAppBase(path).split('#')[0])
}

const AUTH_STORAGE_KEYS = new Set([
  'api_key',
  'user_info',
  'admin_token',
  'yovole_token',
  'token',
  'yovole_embed_token',
])

export function authStorageKey(key: string): string {
  const base = getAppBasePath()
  if (!base || !AUTH_STORAGE_KEYS.has(key)) return key
  return `${base.slice(1)}:${key}`
}

let storagePatched = false

function installAuthStoragePrefix(): void {
  if (typeof window === 'undefined' || storagePatched || !getAppBasePath()) return
  storagePatched = true
  const originalGet = Storage.prototype.getItem
  const originalSet = Storage.prototype.setItem
  const originalRemove = Storage.prototype.removeItem
  const storagePrefix = `${getAppBasePath().slice(1)}:`
  Storage.prototype.getItem = function (key: string) {
    return originalGet.call(this, authStorageKey(key))
  }
  Storage.prototype.setItem = function (key: string, value: string) {
    return originalSet.call(this, authStorageKey(key), value)
  }
  Storage.prototype.removeItem = function (key: string) {
    return originalRemove.call(this, authStorageKey(key))
  }
  Storage.prototype.clear = function () {
    const toRemove: string[] = []
    for (let i = 0; i < this.length; i += 1) {
      const key = this.key(i)
      if (key && key.startsWith(storagePrefix)) toRemove.push(key)
    }
    toRemove.forEach((key) => originalRemove.call(this, key))
  }
}

function rewriteFetchInput(input: RequestInfo | URL): RequestInfo | URL {
  if (typeof input === 'string') return withAppBase(input)
  if (input instanceof URL) {
    const next = withAppBase(`${input.pathname}${input.search}${input.hash}`)
    if (next === `${input.pathname}${input.search}${input.hash}`) return input
    return new URL(next, input.origin)
  }
  if (typeof Request !== 'undefined' && input instanceof Request) {
    const rewritten = withAppBase(input.url)
    if (rewritten === input.url) return input
    return new Request(rewritten, input)
  }
  return input
}

let fetchPatched = false
let eventSourcePatched = false

function installEventSourcePrefix(): void {
  if (typeof window === 'undefined' || eventSourcePatched || !getAppBasePath()) return
  if (typeof window.EventSource === 'undefined') return
  eventSourcePatched = true
  const OriginalEventSource = window.EventSource
  window.EventSource = class PatchedEventSource extends OriginalEventSource {
    constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
      const href = typeof url === 'string' ? url : url.toString()
      super(withAppBase(href), eventSourceInitDict)
    }
  } as typeof EventSource
}

export function installAppBase(): void {
  if (typeof window === 'undefined') return
  installAuthStoragePrefix()
  if (!getAppBasePath()) return
  if (!fetchPatched) {
    fetchPatched = true
    const originalFetch = window.fetch.bind(window)
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => originalFetch(rewriteFetchInput(input), init)) as typeof window.fetch
  }
  installEventSourcePrefix()
}

installAuthStoragePrefix()
