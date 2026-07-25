<script lang="ts">
	import type { Diagnostics } from '$lib/api';
	import { humanize, dur, area, hoursLeft } from '$lib/format';
	import { rise } from '$lib/transitions';
	import Switch from '$lib/components/Switch.svelte';
	import { Wind, Droplets, Filter, Brush, Trash2, Radar, Volume2, Radar as Find } from '@lucide/svelte';

	let { diag, onToggle, onEmpty, onMap, onDrive, onVolume, onLocate }: {
		diag: Diagnostics | null;
		onToggle: (name: string, on: boolean) => void;
		onEmpty: () => void;
		onMap: () => void;
		onDrive: (dir: string) => void;
		onVolume: (v: number) => void;
		onLocate: () => void;
	} = $props();

	const TOGGLE_SUB: Record<string, string> = {
		auto_boost: 'Ramp up suction on rugs',
		do_not_disturb: 'Stay quiet through the night',
		child_lock: 'Ignore the on-device buttons',
		y_mop: 'Scrub in a Y motion',
		vibration: 'Vibrate the mop pad',
		customize_mode: 'Run your saved custom clean',
		dust_collect: 'Empty into the base after cleaning'
	};
	const CONSUMABLE_ICON: Record<string, any> = {
		'Side brush': Wind, 'Main brush': Brush, Filter: Filter, 'Mop cloth': Droplets
	};

	function lifetime() {
		const t = (diag?.totals ?? {}) as any;
		return [
			{ label: 'Cleaned', v: area(t.total_area?.value ?? 0), sub: 'all time' },
			{ label: 'Runs', v: String(t.total_cleans?.value ?? 0), sub: 'completed' },
			{ label: 'Runtime', v: dur(t.total_time?.value ?? 0), sub: 'on the floor' }
		];
	}
</script>

<div class="flex flex-col gap-5">
	<!-- utilities -->
	<div class="grid grid-cols-2 gap-3" in:rise={{ delay: 40 }}>
		<button class="bigtile" onclick={onEmpty}>
			<Trash2 class="size-5 text-primary" />
			<div><p class="text-sm font-medium">Empty the bin</p><p class="text-xs text-muted-foreground">run the base now</p></div>
		</button>
		<button class="bigtile" onclick={onMap}>
			<Radar class="size-5 text-primary" />
			<div><p class="text-sm font-medium">Map the home</p><p class="text-xs text-muted-foreground">fresh scan, no clean</p></div>
		</button>
	</div>

	<!-- consumables + lifetime -->
	<div class="grid gap-5 lg:grid-cols-2">
		{#if diag?.consumables?.length}
			<section class="glass p-5" in:rise={{ delay: 80 }}>
				<h2 class="headline mb-4 text-base font-semibold">Parts &amp; wear</h2>
				<div class="flex flex-col gap-4">
					{#each diag.consumables as c}
						{@const Ic = CONSUMABLE_ICON[c.name] ?? Filter}
						<div class="flex items-center gap-3">
							<div class="grid size-9 shrink-0 place-items-center rounded-lg bg-white/5 text-muted-foreground">
								<Ic class="size-4" />
							</div>
							<div class="min-w-0 flex-1">
								<div class="mb-1.5 flex items-baseline justify-between gap-2">
									<span class="text-sm font-medium">{c.name}</span>
									<span class="text-xs text-muted-foreground tabular">{hoursLeft(c.hours_left)} left</span>
								</div>
								<div class="h-1.5 overflow-hidden rounded-full bg-white/10">
									<div class="h-full rounded-full transition-all duration-700
										{c.percent > 40 ? 'bg-emerald-500' : c.percent > 15 ? 'bg-amber-500' : 'bg-rose-500'}"
										style="width:{Math.max(3, Math.min(100, c.percent))}%"></div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			</section>
		{/if}

		<section class="glass p-5" in:rise={{ delay: 120 }}>
			<h2 class="headline mb-4 text-base font-semibold">All time</h2>
			<div class="grid grid-cols-3 gap-2.5">
				{#each lifetime() as stat}
					<div class="tile p-4 text-center">
						<p class="display text-2xl font-semibold tabular">{stat.v}</p>
						<p class="mt-1 text-xs font-medium">{stat.label}</p>
						<p class="text-[11px] text-muted-foreground">{stat.sub}</p>
					</div>
				{/each}
			</div>
			<div class="mt-4 flex items-center gap-2 rounded-xl border p-3
				{diag?.faults?.length ? 'border-rose-500/30 bg-rose-500/5' : 'border-emerald-500/20 bg-emerald-500/5'}">
				{#if diag?.faults?.length}
					<span class="size-2 rounded-full bg-rose-400"></span>
					<span class="text-sm">Needs attention: {diag.faults.map(humanize).join(', ')}</span>
				{:else}
					<span class="size-2 rounded-full bg-emerald-400"></span>
					<span class="text-sm text-muted-foreground">Everything checks out — no faults.</span>
				{/if}
			</div>
		</section>
	</div>

	<!-- modes -->
	{#if diag?.toggles && Object.keys(diag.toggles).length}
		<section class="glass p-5" in:rise={{ delay: 160 }}>
			<h2 class="headline mb-4 text-base font-semibold">Modes</h2>
			<div class="grid gap-2.5 sm:grid-cols-2">
				{#each Object.entries(diag.toggles) as [name, t]}
					<div class="tile flex items-center gap-3 p-3.5">
						<div class="min-w-0 flex-1">
							<p class="text-sm font-medium">{t.label}</p>
							<p class="truncate text-xs text-muted-foreground">{TOGGLE_SUB[name] ?? ''}</p>
						</div>
						<Switch checked={t.on} onchange={(v) => onToggle(name, v)} />
					</div>
				{/each}
			</div>
		</section>
	{/if}

	<!-- recovery: only needed when it's stuck or lost, so it lives out of the way -->
	<section class="glass p-5" in:rise={{ delay: 200 }}>
		<h2 class="headline text-base font-semibold">Stuck or lost?</h2>
		<p class="mb-4 mt-1 text-sm text-muted-foreground">Make it beep to find it, or drive it out by hand — never lift it, that wipes the map.</p>
		<div class="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:gap-8">
			<div class="mx-auto grid w-44 shrink-0 grid-cols-3 gap-2">
				<span></span>
				<button class="dpad" onclick={() => onDrive('forward')}>↑</button>
				<span></span>
				<button class="dpad" onclick={() => onDrive('turn_left')}>←</button>
				<button class="dpad stop" onclick={() => onDrive('stop')}>■</button>
				<button class="dpad" onclick={() => onDrive('turn_right')}>→</button>
				<span></span>
				<button class="dpad" onclick={() => onDrive('backward')}>↓</button>
				<span></span>
			</div>
			<div class="flex w-full flex-col gap-3">
				<button class="bigtile w-full" onclick={onLocate}>
					<Find class="size-5 text-primary" />
					<div><p class="text-sm font-medium">Make it beep</p><p class="text-xs text-muted-foreground">so you can find it</p></div>
				</button>
				<div class="tile flex items-center gap-3 p-3.5">
					<Volume2 class="size-4 text-muted-foreground" />
					<input type="range" min="0" max="100" step="10" class="flex-1"
						value={diag?.settings?.volume ?? 100}
						onchange={(e) => onVolume(+(e.currentTarget as HTMLInputElement).value)} />
					<span class="w-8 text-right text-xs text-muted-foreground tabular">{diag?.settings?.volume ?? 100}</span>
				</div>
			</div>
		</div>
	</section>
</div>

<style>
	.bigtile {
		display: flex; align-items: center; gap: .65rem; text-align: left;
		padding: .85rem; border-radius: .9rem;
		background: hsl(210 40% 98% / 0.05); border: 1px solid hsl(210 40% 98% / 0.06);
		transition: background .2s, border-color .2s;
	}
	.bigtile:hover { background: hsl(210 40% 98% / 0.09); border-color: hsl(199 89% 60% / 0.3); }
	.dpad {
		display: grid; place-items: center; aspect-ratio: 1; border-radius: .8rem;
		background: hsl(217 19% 22%); font-size: 1.1rem; color: var(--color-foreground);
		transition: background .18s;
	}
	.dpad:hover { background: hsl(217 19% 28%); }
	.dpad.stop { background: hsl(0 60% 40% / .5); color: hsl(0 80% 85%); }
</style>
