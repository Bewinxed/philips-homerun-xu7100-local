<script lang="ts">
	// Native iOS/visionOS toggle. Spring-y knob, tinted track when on.
	let { checked = false, onchange }:
		{ checked?: boolean; onchange?: (v: boolean) => void } = $props();
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	class="track"
	class:on={checked}
	onclick={() => onchange?.(!checked)}
>
	<span class="knob"></span>
</button>

<style>
	.track {
		position: relative;
		width: 46px;
		height: 28px;
		border-radius: 999px;
		background: hsl(217 19% 26%);
		border: 1px solid hsl(210 40% 98% / 0.06);
		box-shadow: inset 0 1px 3px hsl(224 42% 3% / 0.6);
		transition: background 0.28s cubic-bezier(0.22, 1, 0.36, 1);
		cursor: pointer;
		flex: none;
	}
	.track.on {
		background: hsl(152 60% 42%);
		box-shadow: inset 0 1px 3px hsl(152 60% 20% / 0.4), 0 0 12px hsl(152 60% 45% / 0.4);
	}
	.knob {
		position: absolute;
		top: 2.5px;
		left: 2.5px;
		width: 22px;
		height: 22px;
		border-radius: 999px;
		background: white;
		box-shadow: 0 2px 5px hsl(224 42% 3% / 0.5);
		transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
	}
	.track.on .knob { transform: translateX(18px); }
	@media (prefers-reduced-motion: reduce) {
		.track, .knob { transition: none; }
	}
</style>
