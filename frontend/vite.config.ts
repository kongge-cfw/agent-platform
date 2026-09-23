import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "path";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const devBase = "/zhiyuan/";
  return {
    base: mode === "production" ? "./" : devBase,
    plugins: [
      vue(),
      ...(mode === "development"
        ? [
            {
              name: "dev-zhiyuan-base",
              transformIndexHtml(html: string) {
                return html
                  .replace('<base href="/" />', '<base href="/zhiyuan/" />')
                  .replace(
                    'window.__APP_BASE_PATH__="";',
                    'window.__APP_BASE_PATH__="/zhiyuan";',
                  );
              },
            },
          ]
        : []),
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    esbuild: {
      drop: mode === "production" ? ["console", "debugger"] : [],
    },
    server: {
      port: 7154,
      strictPort: true,
      proxy: {
        // 开发环境把接口转到 8001。生产环境前后端同端口，不走这里。
        "^/(api|mcp|docs|openapi\\.json|\\.well-known|static|branding)": {
          target: "http://127.0.0.1:8001",
          changeOrigin: true,
        },
        "^/zhiyuan/(api|mcp|docs|openapi\\.json|\\.well-known|static|branding)": {
          target: "http://127.0.0.1:8001",
          changeOrigin: true,
        },
      },
    },
  };
});
