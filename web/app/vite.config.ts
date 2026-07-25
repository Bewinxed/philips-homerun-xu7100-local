import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter({
				pages: '../dist',
				assets: '../dist',
				fallback: 'index.html',
				precompress: false,
				strict: false
			})
		})
	],
	server: { proxy: { '/api': 'http://localhost:8787' } }
});
