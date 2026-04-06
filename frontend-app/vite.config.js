import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
export default defineConfig({
    plugins: [react()],
    cacheDir: '.vite',
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    server: {
        port: 5173,
        open: true,
    },
    build: {
        outDir: 'dist',
        sourcemap: false,
        rollupOptions: {
            output: {
                manualChunks: function (id) {
                    if (!id.includes('node_modules'))
                        return undefined;
                    if (id.includes('/reactflow/'))
                        return 'flow';
                    if (id.includes('/react-markdown/') || id.includes('/remark-gfm/'))
                        return 'markdown';
                    if (id.includes('/livekit-client/'))
                        return 'voice';
                    if (id.includes('/@mui/') || id.includes('/@emotion/') || id.includes('/@material-symbols/'))
                        return 'mui';
                    if (id.includes('/lucide-react/') || id.includes('/react-icons/'))
                        return 'icons';
                    if (id.includes('/react-dom/') || id.includes('/react/') || id.includes('/scheduler/'))
                        return 'react-core';
                    if (id.includes('/react-router-dom/') || id.includes('/react-router/') || id.includes('/@remix-run/'))
                        return 'routing';
                    return 'vendor';
                },
            },
        },
    },
});
