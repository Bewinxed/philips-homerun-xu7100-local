<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { Toaster } from 'svelte-sonner';
	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>HomeRun Local</title>
</svelte:head>

<div class="dark min-h-screen">
	{@render children()}
	<Toaster
		theme="dark"
		position="top-center"
		richColors
		toastOptions={{
			style: 'background: hsl(222 32% 14% / 0.72); backdrop-filter: blur(24px) saturate(170%); border: 1px solid hsl(210 40% 98% / 0.1); color: hsl(210 40% 98%);'
		}}
	/>
</div>
