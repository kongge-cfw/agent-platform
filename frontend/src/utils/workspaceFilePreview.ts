import axios from '@/utils/axios'
import { copyToClipboard } from './clipboard'
import { isPlatformRoutedUrl, toAxiosUrl, withAppBase } from './appBase'

export type WorkspaceCanvasType = 'html' | 'code' | 'pdf' | 'csv' | 'image'

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif'])
const TEXT_EXTENSIONS = new Set([
  '.txt', '.md', '.csv', '.json', '.sql', '.py', '.js', '.ts',
  '.sh', '.xml', '.html', '.css', '.yaml', '.yml', '.ini', '.conf',
  '.log', '.env', '.htm',
])
const OFFICE_EXTENSIONS = new Set([
  '.docx', '.doc', '.xlsx', '.xls', '.xlsm', '.pptx', '.ppt',
])

export type CanvasPanelData = {
  type: WorkspaceCanvasType | 'compare' | 'mermaid'
  title: string
  content: string
  sourcePath?: string
  compareContent?: string
  compareTitle?: string
  langName?: string
  runnable?: boolean
}

export function normalizeWorkspacePath(path: string): string {
  return String(path || '').replace(/\\/g, '/').replace(/\/+$/, '')
}

export function isSameWorkspacePreviewPath(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false
  return normalizeWorkspacePath(a) === normalizeWorkspacePath(b)
}

export function getWorkspaceFileExtension(name: string): string {
  const parts = name.split('.')
  if (parts.length < 2) return ''
  return `.${parts.pop()!.toLowerCase()}`
}

export function resolveWorkspaceScriptLanguage(name: string): 'python' | 'shell' | null {
  const ext = getWorkspaceFileExtension(name)
  if (ext === '.py') return 'python'
  if (ext === '.sh' || ext === '.bash') return 'shell'
  return null
}

export function canPreviewWorkspaceFile(name: string): boolean {
  const ext = getWorkspaceFileExtension(name)
  if (!ext) return false
  return (
    ext === '.pdf' ||
    IMAGE_EXTENSIONS.has(ext) ||
    TEXT_EXTENSIONS.has(ext) ||
    OFFICE_EXTENSIONS.has(ext)
  )
}

export function resolveWorkspaceCanvasType(name: string): WorkspaceCanvasType {
  const lower = name.toLowerCase()
  if (lower.endsWith('.csv')) return 'csv'
  if (lower.endsWith('.pdf')) return 'pdf'
  if (/\.(jpe?g|png|gif|webp)$/.test(lower)) return 'image'
  if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html'
  return 'code'
}

export function canWriteWorkspaceFile(name: string): boolean {
  const ext = getWorkspaceFileExtension(name)
  if (!ext) return false
  return TEXT_EXTENSIONS.has(ext)
}

function sanitizeGeneratedFilenameBase(title: string): string {
  const base = String(title || '')
    .replace(/\\/g, '/')
    .split('/')
    .pop()
    ?.replace(/\.[^.]+$/, '')
    .replace(/[^\p{L}\p{N}_-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
  return base || 'generated-file'
}

/** 为没有 sourcePath 的画布内容生成安全、可识别的默认文件名。 */
export function buildGeneratedWorkspaceFilename(
  title: string,
  options?: { language?: string; type?: string },
): string {
  const existingExtension = getWorkspaceFileExtension(title)
  if (existingExtension && TEXT_EXTENSIONS.has(existingExtension)) {
    const filename = String(title || '').replace(/\\/g, '/').split('/').pop() || ''
    return filename || `generated-file${existingExtension}`
  }

  const language = String(options?.language || '').toLowerCase()
  const type = String(options?.type || '').toLowerCase()
  let extension = '.txt'
  if (language === 'python' || language === 'python3') extension = '.py'
  else if (language === 'shell' || language === 'sh' || language === 'bash') extension = '.sh'
  else if (type === 'html' || language === 'html' || /html|xml/i.test(title)) extension = '.html'
  else if (type === 'markdown' || type === 'md' || /markdown|\.md$/i.test(title)) extension = '.md'
  else if (language === 'javascript' || language === 'js') extension = '.js'
  else if (language === 'typescript' || language === 'ts') extension = '.ts'
  else if (language === 'sql') extension = '.sql'
  else if (language === 'css') extension = '.css'
  else if (language === 'json') extension = '.json'

  return `${sanitizeGeneratedFilenameBase(title)}${extension}`
}

export function shouldAttachWorkspaceSourcePath(path: string, name: string): boolean {
  if (!canWriteWorkspaceFile(name)) return false
  const normalized = path.replace(/\\/g, '/')
  return normalized.includes('/agent_workspaces/') || normalized.startsWith('/workspace') || normalized.startsWith('workspace/')
}

export function buildWorkspaceCanvasPayload(path: string, name: string) {
  const scriptLanguage = resolveWorkspaceScriptLanguage(name)
  return {
    type: resolveWorkspaceCanvasType(name),
    title: name || '文件预览',
    content: `canvas://file?path=${encodeURIComponent(path)}`,
    sourcePath: shouldAttachWorkspaceSourcePath(path, name) ? path : undefined,
    langName: scriptLanguage || undefined,
    runnable: !!scriptLanguage,
  }
}

export function resolvePublicUploadsPreviewUrl(path: string): string | null {
  const normalized = path.replace(/\\/g, '/')
  if (normalized.includes('/agent_workspaces/')) return null

  const prefixes = [
    'uploads/',
    '/uploads/',
    'data/uploads/',
    '/data/uploads/',
    'app/data/uploads/',
    '/app/data/uploads/',
  ]
  for (const prefix of prefixes) {
    if (normalized.startsWith(prefix)) {
      return withAppBase(`/static/uploads/${normalized.slice(prefix.length).replace(/^\/+/, '')}`)
    }
  }

  const marker = '/data/uploads/'
  const markerIndex = normalized.indexOf(marker)
  if (markerIndex >= 0) {
    return withAppBase(`/static/uploads/${normalized.slice(markerIndex + marker.length).replace(/^\/+/, '')}`)
  }
  return null
}

/** 已是可直接用于 img/iframe/fetch 的 URL，无需再走 fs preview 转换 */
export function isDirectRenderableUrl(url: string): boolean {
  return (
    url.startsWith('http://') ||
    url.startsWith('https://') ||
    url.startsWith('data:') ||
    url.startsWith('blob:') ||
    url.startsWith('quick:') ||
    url.startsWith('canvas:') ||
    isPlatformRoutedUrl(url)
  )
}

export function resolveFsPreviewUrl(path: string, conversationId?: string | null): string {
  if (!path) return ''
  if (isDirectRenderableUrl(path)) {
    if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('data:') || path.startsWith('blob:') || path.startsWith('quick:') || path.startsWith('canvas:')) {
      return path
    }
    return withAppBase(path)
  }
  const publicUploadUrl = resolvePublicUploadsPreviewUrl(path)
  if (publicUploadUrl) return publicUploadUrl
  const convParam = conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : ''
  return withAppBase(`/api/v1/chat/fs/preview?path=${encodeURIComponent(path)}${convParam}`)
}

function resolveFsPreviewRequestUrl(path: string, conversationId?: string | null): string {
  return toAxiosUrl(resolveFsPreviewUrl(path, conversationId))
}

export function hasWorkspaceGlobPattern(path: string): boolean {
  const name = String(path || '').replace(/\\/g, '/').split('/').pop() || ''
  return /[*?]/.test(name)
}

export function resolveWorkspaceDownloadFilename(
  path: string,
  contentDisposition?: string | null,
): string {
  const header = String(contentDisposition || '')
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      /* ignore malformed header */
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(header)
  if (quoted?.[1]) return quoted[1]
  if (hasWorkspaceGlobPattern(path)) {
    const name = path.replace(/\\/g, '/').split('/').pop() || 'files'
    const stem = name.replace(/[*?]+/g, '').replace(/[_.-]+$/g, '').replace(/\.[^.]+$/, '')
    return `${stem || 'matched-files'}.zip`
  }
  return path.replace(/\\/g, '/').split('/').pop() || 'download'
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const blobUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)
}

async function assertBinaryDownload(blob: Blob, filename: string) {
  const ext = getWorkspaceFileExtension(filename)
  if (!OFFICE_EXTENSIONS.has(ext)) return
  const head = new Uint8Array(await blob.slice(0, 32).arrayBuffer())
  const text = new TextDecoder('utf-8', { fatal: false }).decode(head).trimStart().toLowerCase()
  const isZip = head[0] === 0x50 && head[1] === 0x4b
  if (isZip) return
  if (text.startsWith('<!doctype') || text.startsWith('<html')) {
    throw new Error('下载到的是网页而不是文件，请刷新后重试，并从电脑里选择原始文件重新上传')
  }
  throw new Error('下载内容不是有效的 Office 文档，请从电脑里选择原始文件重新上传')
}

function isZipContentType(contentType: string | undefined): boolean {
  return String(contentType || '').toLowerCase().includes('application/zip')
}

type OpenWorkspacePreviewOptions = {
  path: string
  name: string
  conversationId?: string | null
  showToast: (message: string, type?: 'success' | 'error' | 'warning' | 'info') => void
  onOpen: (data: CanvasPanelData) => void
  activeBlobUrlRef?: { value: string }
}

export async function openWorkspaceFileInCanvas(options: OpenWorkspacePreviewOptions) {
  const { path, name, conversationId, showToast, onOpen, activeBlobUrlRef } = options

  if (!canPreviewWorkspaceFile(name)) {
    showToast('不支持预览该类型的文件', 'error')
    return
  }

  const payload = buildWorkspaceCanvasPayload(path, name)
  const filePath = path
  const resolvedUrl = resolveFsPreviewRequestUrl(filePath, conversationId)
  const ext = getWorkspaceFileExtension(name)

  if (activeBlobUrlRef?.value) {
    try {
      URL.revokeObjectURL(activeBlobUrlRef.value)
    } catch {
      /* ignore */
    }
    activeBlobUrlRef.value = ''
  }

  try {
    if (OFFICE_EXTENSIONS.has(ext) || hasWorkspaceGlobPattern(filePath)) {
      const response = await axios.get(resolvedUrl, { responseType: 'blob' })
      const contentType = String(response.headers?.['content-type'] || '')
      if (OFFICE_EXTENSIONS.has(ext) || isZipContentType(contentType)) {
        const filename = resolveWorkspaceDownloadFilename(
          filePath,
          response.headers?.['content-disposition'],
        )
        triggerBrowserDownload(response.data, filename)
        showToast(`已开始下载 ${filename}`, 'success')
        return
      }
      if (payload.type === 'pdf' || payload.type === 'image' || payload.type === 'csv') {
        const blobUrl = URL.createObjectURL(response.data)
        if (activeBlobUrlRef) activeBlobUrlRef.value = blobUrl
        onOpen({
          type: payload.type,
          title: payload.title,
          content: blobUrl,
        })
        return
      }
      const resText = typeof response.data?.text === 'function'
        ? await response.data.text()
        : String(response.data || '')
      const scriptLanguage = resolveWorkspaceScriptLanguage(name)
      onOpen({
        type: payload.type,
        title: payload.title,
        content: resText,
        sourcePath: shouldAttachWorkspaceSourcePath(path, name) ? path : undefined,
        langName: scriptLanguage || undefined,
        runnable: !!scriptLanguage,
      })
      return
    }

    if (payload.type === 'pdf' || payload.type === 'image' || payload.type === 'csv') {
      const response = await axios.get(resolvedUrl, { responseType: 'blob' })
      const blobUrl = URL.createObjectURL(response.data)
      if (activeBlobUrlRef) activeBlobUrlRef.value = blobUrl
      onOpen({
        type: payload.type,
        title: payload.title,
        content: blobUrl,
      })
      return
    }

    const resText = await axios.get(resolvedUrl).then((res) => res.data)
    const scriptLanguage = resolveWorkspaceScriptLanguage(name)
    onOpen({
      type: payload.type,
      title: payload.title,
      content: resText,
      sourcePath: shouldAttachWorkspaceSourcePath(path, name) ? path : undefined,
      langName: scriptLanguage || undefined,
      runnable: !!scriptLanguage,
    })
  } catch (err: any) {
    console.error('加载工作空间文件失败:', err)
    let errMsg = '加载文件失败'
    if (err.response?.data?.detail) {
      errMsg = err.response.data.detail
    } else if (err.response?.status === 404) {
      errMsg = '预览的文件不存在，请确认路径是否正确。'
    } else if (err.response?.status === 403) {
      errMsg = '安全拦截：无权访问该服务器文件。'
    } else if (err.response?.status === 400) {
      errMsg = err.response?.data?.detail || '不支持预览该类型的文件。'
    } else {
      errMsg = err.message || String(err)
    }
    showToast(errMsg, 'error')
  }
}

export async function openChatAttachmentFile(options: {
  path: string
  name: string
  conversationId?: string | null
  showToast: (message: string, type?: 'success' | 'error' | 'warning' | 'info') => void
  /** 7f070dc5 气泡仍会传入；对话附件继续只下载，避免点 PDF 整页进画布。 */
  preview?: unknown
}) {
  const path = String(options.path || '').trim()
  const name = String(options.name || '').trim() || 'download'
  if (!path) {
    options.showToast('无法打开该文件：缺少路径', 'error')
    return
  }
  // 对话气泡附件一律下载；PDF 预览只留给工作区文件浏览器，避免点附件整页跳进画布。
  await downloadWorkspaceFile({
    path,
    name,
    conversationId: options.conversationId,
    showToast: options.showToast,
  })
}

export async function downloadWorkspaceFile(options: {
  path: string
  name: string
  conversationId?: string | null
  showToast: (message: string, type?: 'success' | 'error' | 'warning' | 'info') => void
}) {
  const { path, name, conversationId, showToast } = options
  const resolvedUrl = resolveFsPreviewRequestUrl(path, conversationId)

  try {
    const response = await axios.get(resolvedUrl, { responseType: 'blob' })
    const filename = resolveWorkspaceDownloadFilename(
      path,
      response.headers?.['content-disposition'],
    ) || name || 'download'
    await assertBinaryDownload(response.data, filename)
    triggerBrowserDownload(response.data, filename)
    showToast(`已开始下载 ${filename}`, 'success')
  } catch (err: any) {
    console.error('下载工作空间文件失败:', err)
    let errMsg = '下载文件失败'
    if (err.response?.data?.detail) {
      errMsg = err.response.data.detail
    } else if (err.response?.status === 404) {
      errMsg = '文件不存在，请确认路径是否正确。'
    } else if (err.response?.status === 403) {
      errMsg = '安全拦截：无权访问该服务器文件。'
    } else if (err.response?.status === 400) {
      errMsg = err.response?.data?.detail || '不支持下载该类型的文件。'
    }
    showToast(errMsg, 'error')
  }
}

export async function saveWorkspaceFileContent(options: {
  path: string
  content: string
  conversationId?: string | null
}) {
  const payload: Record<string, string> = {
    path: options.path,
    content: options.content,
  }
  if (options.conversationId) {
    payload.conversation_id = options.conversationId
  }
  return axios.put('/api/v1/chat/fs/write', payload)
}

export async function createWorkspaceEntry(options: {
  parentPath: string
  name: string
  kind: 'file' | 'dir'
  content?: string
}) {
  return axios.post('/api/v1/chat/fs/create-entry', {
    parent_path: options.parentPath,
    name: options.name,
    kind: options.kind,
    content: options.content ?? '',
  })
}

export async function renameWorkspaceEntry(path: string, newName: string) {
  return axios.post('/api/v1/chat/fs/rename-entry', { path, new_name: newName })
}

export async function deleteWorkspaceEntry(path: string) {
  return axios.post('/api/v1/chat/fs/delete-entry', { path })
}

export async function restoreWorkspaceEntry(path: string) {
  return axios.post('/api/v1/chat/fs/restore-entry', { path })
}

export async function purgeWorkspaceEntry(path: string) {
  return axios.post('/api/v1/chat/fs/purge-entry', { path })
}

export async function emptyWorkspaceTrash() {
  return axios.post('/api/v1/chat/fs/empty-trash')
}

export async function uploadToWorkspaceDir(parentPath: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return axios.post('/api/v1/chat/fs/upload', form, {
    params: { parent_path: parentPath },
  })
}

export async function copyTextToClipboard(text: string) {
  const ok = await copyToClipboard(text)
  if (!ok) throw new Error('copy failed')
}
