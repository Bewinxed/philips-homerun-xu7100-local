<script lang="ts">
	// A live, top-down render of the XU7100 sitting on the floor in front of you.
	// It reacts to the robot's real state: the LiDAR turret and side brush spin
	// while it works, a radar wedge sweeps, the status ring changes colour, and
	// it seats on a dock glyph while charging. Pure SVG + CSS so it stays crisp
	// and costs nothing.
	let { state = 'idle', battery = 100, size = 260 }:
		{ state?: string; battery?: number; size?: number } = $props();

	const MOOD: Record<string, { c: string; glow: string; ring: string }> = {
		cleaning:  { c: 'hsl(199 89% 55%)', glow: 'hsl(199 89% 48%)', ring: 'hsl(190 90% 60%)' },
		returning: { c: 'hsl(199 89% 55%)', glow: 'hsl(199 89% 48%)', ring: 'hsl(199 90% 62%)' },
		mapping:   { c: 'hsl(261 70% 62%)', glow: 'hsl(261 70% 55%)', ring: 'hsl(261 80% 68%)' },
		localize:  { c: 'hsl(261 70% 62%)', glow: 'hsl(261 70% 55%)', ring: 'hsl(261 80% 68%)' },
		charging:  { c: 'hsl(152 60% 50%)', glow: 'hsl(152 60% 45%)', ring: 'hsl(152 66% 55%)' },
		docked:    { c: 'hsl(152 60% 50%)', glow: 'hsl(152 60% 45%)', ring: 'hsl(152 66% 55%)' },
		paused:    { c: 'hsl(38 92% 55%)',  glow: 'hsl(38 92% 50%)',  ring: 'hsl(38 95% 60%)' },
		error:     { c: 'hsl(0 75% 58%)',   glow: 'hsl(0 72% 51%)',   ring: 'hsl(0 80% 62%)' },
		idle:      { c: 'hsl(215 25% 62%)', glow: 'hsl(215 25% 45%)', ring: 'hsl(215 25% 55%)' }
	};

	const mood = $derived(MOOD[state] ?? MOOD.idle);
	const active = $derived(['cleaning', 'returning', 'mapping', 'localize'].includes(state));
	const charging = $derived(state === 'charging' || state === 'docked');
	const error = $derived(state === 'error');
</script>

<div class="wrap" style="width:{size}px;height:{size}px"
	style:--c={mood.c} style:--glow={mood.glow} style:--ring={mood.ring}
	class:is-active={active} class:is-charging={charging} class:is-error={error}
	class:is-paused={state === 'paused'}>
	<svg viewBox="0 0 240 240" width={size} height={size} aria-label="robot vacuum, {state}">
		<defs>
			<radialGradient id="body" cx="38%" cy="32%" r="80%">
				<stop offset="0%" stop-color="hsl(210 22% 92%)" />
				<stop offset="45%" stop-color="hsl(214 16% 80%)" />
				<stop offset="100%" stop-color="hsl(217 20% 60%)" />
			</radialGradient>
			<radialGradient id="plate" cx="42%" cy="35%" r="75%">
				<stop offset="0%" stop-color="hsl(216 16% 30%)" />
				<stop offset="100%" stop-color="hsl(220 20% 16%)" />
			</radialGradient>
			<radialGradient id="dome" cx="38%" cy="30%" r="80%">
				<stop offset="0%" stop-color="hsl(210 18% 46%)" />
				<stop offset="100%" stop-color="hsl(218 22% 22%)" />
			</radialGradient>
			<filter id="soft"><feGaussianBlur stdDeviation="6" /></filter>
		</defs>

		<!-- floor shadow: grounds it "on the floor in front of you" -->
		<ellipse cx="120" cy="214" rx="78" ry="16" fill="hsl(224 60% 3%)" opacity="0.55" filter="url(#soft)" />

		<!-- dock glyph, only while charging/docked -->
		<g class="dock" opacity="0">
			<rect x="92" y="196" width="56" height="16" rx="5" fill="hsl(222 28% 22%)" />
			<rect x="112" y="182" width="16" height="20" rx="3" fill="hsl(222 28% 26%)" />
		</g>

		<!-- ambient state glow behind the body -->
		<circle class="ambient" cx="120" cy="118" r="96" fill="var(--glow)" opacity="0.28" filter="url(#soft)" />

		<!-- status / radar ring -->
		<circle class="ring" cx="120" cy="118" r="104" fill="none" stroke="var(--ring)"
			stroke-width="2.5" stroke-linecap="round" opacity="0.9" />
		<circle class="ring-pulse" cx="120" cy="118" r="104" fill="none" stroke="var(--ring)"
			stroke-width="2" opacity="0" />

		<!-- body -->
		<g class="body">
			<circle cx="120" cy="118" r="88" fill="url(#body)" stroke="hsl(220 20% 55%)" stroke-width="1" />
			<!-- front bumper seam (top = forward) -->
			<path d="M 52 96 A 88 88 0 0 1 188 96" fill="none"
				stroke="hsl(220 18% 52%)" stroke-width="6" opacity="0.5" stroke-linecap="round" />
			<!-- top plate -->
			<circle cx="120" cy="118" r="66" fill="url(#plate)" stroke="hsl(220 24% 34%)" stroke-width="1" />

			<!-- radar sweep wedge (only visible when active) -->
			<g class="sweep">
				<path d="M 120 118 L 120 44 A 74 74 0 0 1 175 68 Z" fill="var(--c)" opacity="0.16" />
			</g>

			<!-- LiDAR turret: the spinning part -->
			<g class="turret">
				<circle cx="120" cy="118" r="30" fill="url(#dome)" stroke="hsl(220 24% 40%)" stroke-width="1.5" />
				<!-- window slit so rotation reads -->
				<rect x="117" y="90" width="6" height="18" rx="3" fill="hsl(199 89% 60%)" opacity="0.85" />
				<circle cx="120" cy="118" r="6" fill="hsl(214 14% 78%)" />
			</g>
		</g>

		<!-- side brush (bottom-right), spins when working -->
		<g class="sidebrush">
			{#each [0, 72, 144, 216, 288] as a}
				<line x1="176" y1="170" x2="176" y2="152" stroke="hsl(210 16% 82%)"
					stroke-width="2.5" stroke-linecap="round"
					transform="rotate({a} 176 170)" />
			{/each}
			<circle cx="176" cy="170" r="4" fill="hsl(216 16% 40%)" />
		</g>

		<!-- charging bolt (shown only on the dock; the turret hides so nothing overlaps) -->
		<path class="bolt" d="M 125 99 L 111 121 L 120 121 L 115 137 L 131 113 L 121 113 Z"
			fill="hsl(152 70% 62%)" opacity="0" />

		<!-- error mark -->
		<g class="warn" opacity="0">
			<path d="M120 96 L138 128 L102 128 Z" fill="none" stroke="var(--c)" stroke-width="4" stroke-linejoin="round" />
			<line x1="120" y1="108" x2="120" y2="119" stroke="var(--c)" stroke-width="4" stroke-linecap="round" />
			<circle cx="120" cy="124" r="1.6" fill="var(--c)" />
		</g>
	</svg>
</div>

<style>
	.wrap { position: relative; display: grid; place-items: center; }
	svg { overflow: visible; }

	/* idle: turret drifts slowly; active: it spins with purpose */
	.turret { transform-box: view-box; transform-origin: 120px 118px; animation: spin 14s linear infinite; }
	.is-active .turret { animation-duration: 2.4s; }
	.is-paused .turret { animation-play-state: paused; }
	.is-charging .turret { display: none; } /* on the dock: bolt takes the center, no overlap */

	.sidebrush { transform-box: view-box; transform-origin: 176px 170px; opacity: 0; }
	.is-active .sidebrush { opacity: 1; animation: spin 1.1s linear infinite reverse; }

	.sweep { transform-box: view-box; transform-origin: 120px 118px; opacity: 0; }
	.is-active .sweep { opacity: 1; animation: spin 2.4s linear infinite; }

	/* the status ring: dashed sweeping arc when active, calm hairline otherwise */
	.ring {
		transform-box: view-box; transform-origin: 120px 118px;
		stroke-dasharray: 40 620; transition: stroke .4s;
	}
	.is-active .ring { animation: spin 3.2s linear infinite; }
	:global(.is-charging) .ring { stroke-dasharray: 4 12; opacity: 0.7; }

	.ring-pulse { transform-box: view-box; transform-origin: 120px 118px; }
	.is-charging .ring-pulse, .is-error .ring-pulse { animation: pulse 1.8s ease-out infinite; }
	.is-error .ring-pulse { animation-duration: 1s; }

	.ambient { transition: fill .4s; }
	.is-charging .ambient, .is-error .ambient { animation: breathe 2.4s ease-in-out infinite; }
	.is-error .ambient { animation-duration: 1s; }

	.is-charging .bolt { opacity: 1; animation: breathe 1.8s ease-in-out infinite; }
	.is-charging .dock { opacity: 1; }
	.is-error .warn { opacity: 1; }
	.is-error .turret { display: none; }

	/* a small physical wobble when it hits an error, then settles */
	.is-error .body { animation: nudge 0.9s ease-in-out infinite; transform-box: view-box; transform-origin: 120px 118px; }

	@keyframes spin { to { transform: rotate(360deg); } }
	@keyframes pulse {
		0% { transform: scale(0.86); opacity: 0.7; }
		100% { transform: scale(1.14); opacity: 0; }
	}
	@keyframes breathe { 0%,100% { opacity: 0.6; } 50% { opacity: 1; } }
	@keyframes nudge { 0%,100% { transform: rotate(-1.5deg); } 50% { transform: rotate(1.5deg); } }

	@media (prefers-reduced-motion: reduce) {
		.turret, .sidebrush, .sweep, .ring, .ring-pulse, .ambient, .bolt, .body { animation: none !important; }
	}
</style>
