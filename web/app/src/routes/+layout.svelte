<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { Toaster } from 'svelte-sonner';
	let { children } = $props();

	// The backend answers 401 when this browser isn't on a trusted network and
	// hasn't sent the API token (backend/access.py). Ask for it once and keep it
	// as a same-site cookie, which every API call and the event stream send.
	if (typeof window !== 'undefined' && !(window as any).__homerunAuth) {
		(window as any).__homerunAuth = true;
		const orig = window.fetch.bind(window);
		let asked = false;
		window.fetch = async (input, init) => {
			const r = await orig(input, init);
			if (r.status === 401 && !asked) {
				asked = true;
				const token = window.prompt('HomeRun Local API token (see the api_token file next to config.json):');
				if (token) {
					document.cookie = `homerun_token=${encodeURIComponent(token.trim())}; path=/; SameSite=Strict`
						+ (location.protocol === 'https:' ? '; Secure' : '');
					location.reload();
				}
			}
			return r;
		};
	}
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
