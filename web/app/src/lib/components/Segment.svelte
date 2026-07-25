<script lang="ts">
	// Native segmented control. The thumb slides under the active label with a
	// spring settle; the whole track is one inner surface, not stacked glass.
	let { options, value, onchange }: {
		options: { value: string; label: string }[];
		value: string;
		onchange?: (v: string) => void;
	} = $props();

	const idx = $derived(Math.max(0, options.findIndex((o) => o.value === value)));
	const n = $derived(options.length);
</script>

<div class="seg tile" style="grid-template-columns: repeat({n}, 1fr)">
	<span class="thumb" style="width: calc((100% - 8px) / {n}); transform: translateX({idx * 100}%)"></span>
	{#each options as o}
		<button type="button" class="opt" data-active={o.value === value} onclick={() => onchange?.(o.value)}>
			{o.label}
		</button>
	{/each}
</div>

<style>
	.seg {
		position: relative;
		display: grid;
		padding: 4px;
		border-radius: 999px;
		gap: 0;
	}
	.thumb {
		position: absolute;
		top: 4px;
		bottom: 4px;
		left: 4px;
		border-radius: 999px;
		background: hsl(199 89% 48% / 0.9);
		box-shadow: inset 0 1px 0 hsl(0 0% 100% / 0.25), 0 4px 14px hsl(199 89% 40% / 0.35);
		/* spring-ish settle, no jarring linear slide */
		transition: transform 0.42s cubic-bezier(0.34, 1.4, 0.5, 1);
	}
	.opt {
		position: relative;
		z-index: 1;
		border-radius: 999px;
		padding: 0.5rem 0.25rem;
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--color-muted-foreground);
		transition: color 0.25s;
	}
	.opt[data-active='true'] { color: hsl(222 47% 11%); }
	@media (prefers-reduced-motion: reduce) { .thumb { transition: none; } }
</style>
