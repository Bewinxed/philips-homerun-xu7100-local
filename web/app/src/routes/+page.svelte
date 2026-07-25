<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		api, diagnostics, startMapping, drive, toggle, setVolume,
		mapVector, cleanRooms, renameRoom, mergeRooms, unmergeRoom, splitRoom, unsplitRoom, roomAttrs, emptyBin,
		type RobotState, type MapMeta, type Diagnostics
	} from '$lib/api';
	import { area, dur } from '$lib/format';
	import { materialize, rise } from '$lib/transitions';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import Segment from '$lib/components/Segment.svelte';
	import MapView from '$lib/MapView.svelte';
	import RobotAvatar from '$lib/RobotAvatar.svelte';
	import VoiceStudio from '$lib/VoiceStudio.svelte';
	import CareTab from '$lib/panels/CareTab.svelte';
	import {
		Play, Pause, Square, House, Radar, RotateCw, Wifi, WifiOff, Wind, Droplets,
		Sparkles, Wrench, Wand2, Pencil, Check
	} from '@lucide/svelte';

	type Tab = 'home' | 'care' | 'voice';
	const TABS: { id: Tab; label: string; icon: any }[] = [
		{ id: 'home', label: 'Home', icon: House },
		{ id: 'care', label: 'Care', icon: Wrench },
		{ id: 'voice', label: 'Voice', icon: Wand2 }
	];
	let tab = $state<Tab>('home');
	const tabIdx = $derived(TABS.findIndex((t) => t.id === tab));

	let s = $state<RobotState | null>(null);
	let diag = $state<Diagnostics | null>(null);
	let vec = $state<any>(null);
	let selected = $state<Set<number>>(new Set());
	let editingId = $state<number | null>(null);
	let editVal = $state('');

	async function reloadVector(force = false) { try { vec = await mapVector(force); } catch {} }

	const SUCTION = [
		{ value: 'gentle', label: 'Gentle' }, { value: 'normal', label: 'Normal' },
		{ value: 'strong', label: 'Strong' }, { value: 'max', label: 'Max' }
	];
	const WATER = [
		{ value: 'closed', label: 'Off' }, { value: 'low', label: 'Low' },
		{ value: 'middle', label: 'Medium' }, { value: 'high', label: 'High' }
	];
	function suctionValue(v: string | null | undefined) {
		const k = (v ?? '').toLowerCase();
		if (['gentle', 'quiet'].includes(k)) return 'gentle';
		if (['normal', 'standard'].includes(k)) return 'normal';
		if (k === 'strong') return 'strong';
		if (['max', 'turbo'].includes(k)) return 'max';
		return 'gentle';
	}

	const stateLabel: Record<string, string> = {
		idle: 'Idle', cleaning: 'Cleaning', paused: 'Paused',
		returning: 'Heading to dock', docked: 'Docked', charging: 'Charging', error: 'Needs a hand'
	};
	const stateColor: Record<string, string> = {
		cleaning: 'text-primary', returning: 'text-primary', charging: 'text-emerald-400',
		docked: 'text-emerald-400', paused: 'text-amber-400', error: 'text-rose-400',
		idle: 'text-muted-foreground'
	};
	const stateHint: Record<string, string> = {
		idle: 'Waiting for you', cleaning: 'On the floor, working', paused: 'Paused mid-run',
		returning: 'On the way back to the base', docked: 'Parked and topped up',
		charging: 'Sipping power on the base', error: 'Something needs checking'
	};

	const CMD_MSG: Record<string, string> = {
		start: 'Starting the clean', pause: 'Pausing', stop: 'Stopping',
		home: 'Sending it home', locate: 'Making it beep'
	};
	async function cmd(action: string) {
		toast(CMD_MSG[action] ?? '…'); // feedback on the press, not when SSE catches up
		try { await api.command(action); } catch { toast.error("Couldn't reach the robot"); }
	}

	async function runRooms() {
		const names = [...selected].map((id) => vec?.rooms.find((r: any) => r.id === id)?.name).filter(Boolean);
		toast(`Cleaning ${names.join(', ') || 'selected rooms'}`);
		await cleanRooms([...selected], 1);
	}
	async function doMerge() {
		const ids = [...selected];
		// merge them all pairwise into one group
		for (let i = 1; i < ids.length; i++) await mergeRooms(ids[0], ids[i]);
		toast.success('Merged into one room');
		selected = new Set();
		await reloadVector(true);
	}
	async function doUnmerge(id: number) {
		await unmergeRoom(id);
		toast('Split back apart');
		await reloadVector(true);
	}
	// context-menu actions from the map
	function ctxRename(id: number) {
		const room = vec?.rooms.find((r: any) => r.id === id);
		if (room) startRename(room);
	}
	async function ctxMerge(id: number) {
		const targets = [...selected].filter((s) => s !== id);
		if (!targets.length) { toast('Select rooms first, then merge'); return; }
		for (const t of targets) await mergeRooms(id, t);
		toast.success('Merged into one room');
		selected = new Set();
		await reloadVector(true);
	}
	async function ctxSplit(id: number, line: number[]) {
		await splitRoom(id, line[0], line[1], line[2], line[3]);
		toast.success('Room split in two');
		await reloadVector(true);
	}
	async function ctxUnsplit(id: number) {
		await unsplitRoom(id);
		toast('Split undone');
		await reloadVector(true);
	}
	async function ctxCleanRoom(id: number) {
		const room = vec?.rooms.find((r: any) => r.id === id);
		toast(`Cleaning ${room?.name ?? 'room'}`);
		await cleanRooms([id], 1);
	}
	// collapse merged rooms into one row per group for the per-room list
	function roomGroups() {
		const rooms = vec?.rooms ?? [];
		const by = new Map<number, any>();
		for (const r of rooms) {
			const g = r.group ?? r.id;
			if (!by.has(g)) by.set(g, { root: r, members: [], area: 0, merged: false });
			const grp = by.get(g);
			grp.members.push(r);
			grp.area += r.area_m2;
			if (r.id === g) grp.root = r;
			if (grp.members.length > 1) grp.merged = true;
		}
		return [...by.values()];
	}
	function startRename(room: any) { editingId = room.id; editVal = room.name; }
	async function commitRename() {
		if (editingId == null) return;
		const room = vec?.rooms.find((r: any) => r.id === editingId);
		const name = editVal.trim();
		editingId = null;
		if (room && name && name !== room.name) {
			room.name = name; vec = { ...vec };
			await renameRoom(room.id, name);
			toast(`Renamed to "${name}"`);
			setTimeout(() => reloadVector(true), 3000);
		}
	}
	async function setGroup(grp: any, patch: { fan?: string; passes?: number }) {
		for (const room of grp.members) {
			await roomAttrs(room.id, patch.fan ?? room.settings.fan, room.settings.water, patch.passes ?? room.settings.sweep_count);
			if (patch.fan) room.settings.fan = patch.fan;
			if (patch.passes) room.settings.sweep_count = patch.passes;
		}
		vec = { ...vec };
	}

	async function doEmpty() { toast('Emptying into the base'); await emptyBin(); }
	async function doMap() { toast('Starting a fresh map'); await startMapping(); }
	async function doDrive(dir: string) { await drive(dir); }
	async function doToggle(name: string, on: boolean) { await toggle(name, on); diag = await diagnostics(); }
	async function doVolume(v: number) { await setVolume(v); toast(`Volume ${v}%`); }
	async function refreshMap() { await api.mapMeta(true); await reloadVector(true); }

	onMount(() => {
		api.state().then((v) => (s = v));
		const es = new EventSource('/api/events');
		es.onmessage = (e) => { try { s = JSON.parse(e.data); } catch {} };
		es.onerror = () => {};
		refreshMap();
		diagnostics().then((v) => (diag = v)).catch(() => {});
		const mapTimer = setInterval(() => reloadVector(), 8000);
		const diagTimer = setInterval(() => diagnostics().then((v) => (diag = v)).catch(() => {}), 15000);
		return () => { es.close(); clearInterval(mapTimer); clearInterval(diagTimer); };
	});

	const st = $derived(s?.state ?? 'idle');
	const isRunning = $derived(st === 'cleaning' || st === 'returning');
	const battery = $derived(s?.battery ?? 100);
	const batteryColor = $derived(battery <= 20 ? 'hsl(38 92% 55%)' : 'hsl(152 60% 50%)');
	const CIRC = 2 * Math.PI * 24;
</script>

<div class="mx-auto max-w-5xl px-4 py-6 md:py-9">
	<!-- header -->
	<header class="flex items-center justify-between gap-4">
		<div class="flex items-center gap-3">
			<div class="grid size-11 place-items-center rounded-2xl bg-primary/15 text-primary ring-1 ring-primary/20">
				<Radar class="size-6" />
			</div>
			<div>
				<h1 class="text-xl font-semibold">Subhiyya</h1>
				<p class="text-sm text-muted-foreground">Philips HomeRun · XU7100</p>
			</div>
		</div>
		<div class="flex items-center gap-2">
			<Badge variant={s?.source === 'robot' ? 'default' : 'secondary'}>{s?.source === 'robot' ? 'LIVE' : 'SIM'}</Badge>
			{#if s?.connected}
				<span class="flex items-center gap-1 text-sm text-emerald-400"><Wifi class="size-4" /> online</span>
			{:else}
				<span class="flex items-center gap-1 text-sm text-muted-foreground"><WifiOff class="size-4" /> offline</span>
			{/if}
		</div>
	</header>

	<!-- tabs -->
	<div class="mt-6 flex justify-center">
		<div class="seg glass">
			<span class="seg-thumb" style="width:6.25rem; transform: translateX({tabIdx * 6.25}rem)"></span>
			{#each TABS as t}
				<button class="seg-btn" style="min-width:6.25rem; text-align:center" data-active={tab === t.id} onclick={() => (tab = t.id)}>
					<span class="inline-flex items-center gap-1.5"><t.icon class="size-4" /> {t.label}</span>
				</button>
			{/each}
		</div>
	</div>

	{#key tab}
		<div in:materialize={{ duration: 440 }}>
			{#if tab === 'home'}
				<!-- status capsule -->
				<div class="glass glass-strong mt-6 flex items-center gap-5 p-5" in:rise={{ delay: 30 }}>
					<RobotAvatar state={st} {battery} size={104} />
					<div class="min-w-0 flex-1">
						<p class="text-2xl font-semibold {stateColor[st]}">{stateLabel[st]}</p>
						<p class="truncate text-sm text-muted-foreground">{stateHint[st]}</p>
						{#if isRunning}
							<p class="mt-0.5 text-sm text-muted-foreground tabular">{area(s?.clean_area ?? 0)} · {dur(s?.clean_time ?? 0)} this run</p>
						{/if}
					</div>
					<div class="relative grid size-[68px] shrink-0 place-items-center">
						<svg viewBox="0 0 60 60" class="size-[68px] -rotate-90">
							<circle cx="30" cy="30" r="24" fill="none" stroke="hsl(217 19% 22%)" stroke-width="5" />
							<circle cx="30" cy="30" r="24" fill="none" stroke={batteryColor} stroke-width="5" stroke-linecap="round"
								stroke-dasharray="{(battery / 100) * CIRC} {CIRC}" style="transition: stroke-dasharray .6s cubic-bezier(.22,1,.36,1)" />
						</svg>
						<div class="absolute text-center">
							<div class="text-base font-semibold leading-none tabular">{battery}<span class="text-[10px]">%</span></div>
							<div class="text-[9px] text-muted-foreground">{st === 'charging' ? 'charging' : 'battery'}</div>
						</div>
					</div>
				</div>

				<!-- action bar: transport-style, primary Start/Pause + secondaries -->
				<div class="mt-4 flex gap-3" in:rise={{ delay: 70 }}>
					<button class="act-primary" onclick={() => cmd(isRunning ? 'pause' : 'start')}>
						{#if isRunning}<Pause class="size-5" /> Pause{:else}<Play class="size-5" /> Start{/if}
					</button>
					<button class="act-icon" onclick={() => cmd('stop')}><Square class="size-5" /><span>Stop</span></button>
					<button class="act-icon" onclick={() => cmd('home')}><House class="size-5" /><span>Dock</span></button>
					<button class="act-icon" onclick={() => cmd('locate')}><Radar class="size-5" /><span>Find</span></button>
				</div>

				<!-- the map is the canvas -->
				<section class="glass mt-4 overflow-hidden p-4" in:rise={{ delay: 110 }}>
					<div class="mb-3 flex items-center justify-between px-1">
						<h2 class="headline text-base font-semibold">Home map</h2>
						<button class="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground" onclick={refreshMap}>
							<RotateCw class="size-4" /> Refresh
						</button>
					</div>
					<MapView {vec} bind:selected
						onrename={ctxRename} onmerge={ctxMerge} onunmerge={doUnmerge}
						onsplit={ctxSplit} onunsplit={ctxUnsplit} oncleanroom={ctxCleanRoom} />

					{#if vec?.ok}
						<div class="mt-3 flex flex-wrap items-center gap-2">
							<span class="text-sm text-muted-foreground">{selected.size ? `${selected.size} selected` : 'Tap rooms on the map to clean just those'}</span>
							{#if selected.size}
								<Button size="sm" onclick={runRooms}><Play class="size-4" /> Clean selected</Button>
								<Button size="sm" variant="secondary" onclick={() => (selected = new Set())}>Clear</Button>
							{/if}
							{#if selected.size === 2}<Button size="sm" variant="outline" onclick={doMerge}>Merge</Button>{/if}
						</div>
					{/if}
				</section>

				<!-- this clean: settings that act on the map above -->
				<section class="glass mt-4 p-5" in:rise={{ delay: 150 }}>
					<h2 class="headline mb-4 text-base font-semibold">This clean</h2>
					<div class="grid gap-5 sm:grid-cols-2">
						<div>
							<div class="mb-2 flex items-center gap-2 text-sm text-muted-foreground"><Wind class="size-4" /> Suction</div>
							<Segment options={SUCTION} value={suctionValue(s?.fan)} onchange={(v) => { api.fan(v); }} />
						</div>
						<div>
							<div class="mb-2 flex items-center gap-2 text-sm text-muted-foreground"><Droplets class="size-4" /> Water</div>
							<Segment options={WATER} value={s?.water ?? 'middle'} onchange={(v) => { api.water(v); }} />
						</div>
					</div>

					{#if vec?.ok && vec.rooms?.length}
						<div class="mt-5 flex flex-col gap-2">
							<p class="text-sm text-muted-foreground">Per-room</p>
							{#each roomGroups() as grp (grp.root.id)}
								{@const room = grp.root}
								<div class="tile flex flex-wrap items-center gap-2 p-2.5 text-sm {selected.has(room.id) ? 'ring-1 ring-primary/40' : ''}">
									{#if editingId === room.id}
										<input class="w-28 rounded-md border border-input bg-background/60 px-2 py-0.5 text-sm" bind:value={editVal}
											onkeydown={(e) => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') editingId = null; }}
											onblur={commitRename} autofocus />
										<button class="text-emerald-400" onclick={commitRename}><Check class="size-4" /></button>
									{:else}
										<button class="group flex min-w-20 items-center gap-1 text-left font-medium" onclick={() => startRename(room)}>
											{room.name}
											<Pencil class="size-3 opacity-0 transition group-hover:opacity-60" />
										</button>
									{/if}
									<span class="text-xs text-muted-foreground tabular">{Math.round(grp.area * 100) / 100} m²</span>
									{#if grp.merged}
										<button class="text-[11px] text-muted-foreground hover:text-rose-400" onclick={() => doUnmerge(room.id)}>unmerge</button>
									{/if}
									<div class="ml-auto flex items-center gap-1">
										{#each SUCTION as f}
											<button class="pill" data-active={room.settings.fan === f.value} onclick={() => setGroup(grp, { fan: f.value })}>{f.label}</button>
										{/each}
										<span class="mx-1 text-border">·</span>
										{#each [1, 2] as p}
											<button class="pill" data-active={room.settings.sweep_count === p} onclick={() => setGroup(grp, { passes: p })}>{p}×</button>
										{/each}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</section>
			{:else if tab === 'care'}
				<div class="mt-6">
					<CareTab {diag} onToggle={doToggle} onEmpty={doEmpty} onMap={doMap} onDrive={doDrive} onVolume={doVolume} onLocate={() => cmd('locate')} />
				</div>
			{:else}
				<div class="mt-6"><VoiceStudio /></div>
			{/if}
		</div>
	{/key}

	<footer class="mt-8 text-center text-xs text-muted-foreground">
		HomeRun Local · live · {s ? new Date(s.last_update * 1000).toLocaleTimeString() : ''}
	</footer>
</div>

<style>
	.act-primary {
		flex: 1 1 0; display: flex; align-items: center; justify-content: center; gap: .5rem;
		padding: 1rem; border-radius: 1rem; font-size: 1rem; font-weight: 600;
		color: hsl(222 47% 11%);
		background: hsl(199 89% 48%);
		box-shadow: inset 0 1px 0 hsl(0 0% 100% / .3), 0 10px 26px -8px hsl(199 89% 45% / .6);
		transition: filter .2s, transform .12s cubic-bezier(.22,1,.36,1);
	}
	.act-primary:hover { filter: brightness(1.06); }

	.act-icon {
		display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .3rem;
		width: 5rem; padding: .75rem .5rem; border-radius: 1rem;
		font-size: .7rem; font-weight: 600; color: var(--color-foreground);
		background: hsl(210 40% 98% / 0.05); border: 1px solid hsl(210 40% 98% / 0.06);
		transition: background .2s, border-color .2s, transform .12s cubic-bezier(.22,1,.36,1);
	}
	.act-icon:hover { background: hsl(210 40% 98% / 0.09); border-color: hsl(199 89% 60% / 0.3); }
	.act-icon span { color: var(--color-muted-foreground); }

	.pill {
		border-radius: 999px; padding: .2rem .55rem; font-size: .72rem; font-weight: 600;
		color: var(--color-muted-foreground); background: hsl(210 40% 98% / 0.05);
		transition: background .18s, color .18s;
	}
	.pill[data-active='true'] { background: hsl(199 89% 48%); color: hsl(222 47% 11%); }
</style>
