import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// fontsource CSS는 woff2와 구형 woff를 함께 가리켜 같은 글꼴이 두 벌 번들된다.
// 앱 웹뷰(WKWebView·WebView2)는 모두 woff2를 지원하므로 woff 폴백을 뺀다.
const stripWoffFallback = {
  name: 'strip-woff-fallback',
  enforce: 'pre' as const,
  transform(code: string, id: string) {
    if (!id.includes('@fontsource') || !id.endsWith('.css')) return null
    return code.replace(/,\s*url\([^)]*\.woff\)\s*format\(['"]woff['"]\)/g, '')
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [stripWoffFallback, react()],
})
