<script lang="ts">
	import { ContextMenu } from 'bits-ui';
	import { Scissors, Pencil, Combine, Split, Play, Ungroup } from '@lucide/svelte';

	let {
		vec = null,
		selected = $bindable(new Set<number>()),
		onpick = (_id: number) => {},
		onrename = (_id: number) => {},
		onmerge = (_id: number) => {},
		onunmerge = (_id: number) => {},
		onsplit = (_id: number, _line: number[]) => {},
		onunsplit = (_id: number) => {},
		oncleanroom = (_id: number) => {},
		floors = [],
		floorId = null,
		onfloor = (_id: number) => {}
	}: {
		vec: any;
		selected?: Set<number>;
		onpick?: (id: number) => void;
		onrename?: (id: number) => void;
		onmerge?: (id: number) => void;
		onunmerge?: (id: number) => void;
		onsplit?: (id: number, line: number[]) => void;
		onunsplit?: (id: number) => void;
		oncleanroom?: (id: number) => void;
		floors?: { id: number; name: string }[];
		floorId?: number | null;
		onfloor?: (id: number) => void;
	} = $props();

	const PALETTE = ['#38bdf8', '#f472b6', '#4ade80', '#fbbf24', '#a78bfa', '#fb923c', '#2dd4bf', '#f87171', '#60a5fa', '#c084fc'];

	let hovered = $state<number | null>(null);
	let zoom = $state(1);
	// Map layers; the legend chips toggle them and the choice is kept per browser
	type Layer = 'walls' | 'nogo' | 'vwalls' | 'route' | 'dock' | 'robot' | 'labels';
	const LAYERS_KEY = 'homerun.map.layers';
	function loadLayers(): Record<Layer, boolean> {
		const all = { walls: true, nogo: true, vwalls: true, route: true, dock: true, robot: true, labels: true };
		try { return { ...all, ...JSON.parse(localStorage.getItem(LAYERS_KEY) ?? '{}') }; } catch { return all; }
	}
	let layers = $state(loadLayers());
	function flip(l: Layer) {
		layers[l] = !layers[l];
		try { localStorage.setItem(LAYERS_KEY, JSON.stringify(layers)); } catch {}
	}
	const NOGO = '#ef4444';
	// legend entries that exist on this floor
	const legend = $derived(
		!vec?.ok ? [] : ([
			{ id: 'walls', label: 'Walls', show: vec.walls?.length },
			{ id: 'nogo', label: 'No-go zones', count: vec.no_go_zones?.length, show: vec.no_go_zones?.length },
			{ id: 'vwalls', label: 'Virtual walls', count: vec.virtual_walls?.length, show: vec.virtual_walls?.length },
			{ id: 'route', label: 'Last route', show: vec.path?.length },
			{ id: 'dock', label: 'Dock', show: vec.charger_px },
			{ id: 'robot', label: 'Last position', show: vec.robot_px },
			{ id: 'labels', label: 'Room names', show: vec.rooms?.length }
		] as { id: Layer; label: string; count?: number; show: unknown }[]).filter((e) => e.show)
	);
	let ctxRoom = $state<any>(null);

	// split mode: click two points on the map to draw the cut line
	let splitting = $state<number | null>(null);
	let p1 = $state<[number, number] | null>(null);
	let cursor = $state<[number, number] | null>(null);
	let gEl: SVGGElement | null = null;

	const ringPath = (rings: number[][][]) => rings.map((r) => 'M' + r.map((p) => `${p[0]} ${p[1]}`).join('L') + 'Z').join(' ');
	const groupOf = (r: any) => r.group ?? r.id;

	function toggle(id: number) {
		if (splitting != null) return;
		const room = vec.rooms.find((r: any) => r.id === id);
		const g = groupOf(room);
		const members = vec.rooms.filter((r: any) => groupOf(r) === g).map((r: any) => r.id);
		const s = new Set(selected);
		const on = members.some((m: number) => s.has(m));
		for (const m of members) on ? s.delete(m) : s.add(m);
		selected = s;
		onpick(id);
	}

	const pathLine = $derived(vec?.path?.length ? 'M' + vec.path.map((p: number[]) => `${p[0]} ${p[1]}`).join('L') : '');

	function toMap(e: { clientX: number; clientY: number }): [number, number] | null {
		if (!gEl) return null;
		const ctm = gEl.getScreenCTM();
		if (!ctm) return null;
		const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
		return [Math.round(pt.x), Math.round(pt.y)];
	}
	function startSplit(id: number) { splitting = id; p1 = null; cursor = null; }
	function cancelSplit() { splitting = null; p1 = null; cursor = null; }
	function splitClick(e: MouseEvent) {
		const p = toMap(e);
		if (!p) return;
		if (!p1) { p1 = p; return; }
		const id = splitting!;
		const line = [p1[0], p1[1], p[0], p[1]];
		cancelSplit();
		onsplit(id, line);
	}
</script>

{#if !vec?.ok}
	<div class="grid aspect-square place-items-center rounded-lg bg-secondary/40 p-6 text-center text-sm text-muted-foreground">
		{vec?.error ?? 'No map yet — run a mapping pass.'}
	</div>
{:else}
	<div class="flex flex-col gap-2">
		<div class="flex items-center gap-2 text-xs text-muted-foreground">
			<span>{vec.size_m[0]}×{vec.size_m[1]} m</span>
			<span class="opacity-50">·</span>
			<span>{vec.resolution_cm} cm/px</span>
			<span class="opacity-50">·</span>
			<span>{vec.rooms.length} rooms</span>
			<div class="ml-auto flex gap-1">
				<button class="rounded px-2 py-0.5 hover:bg-secondary" onclick={() => (zoom = Math.min(4, zoom * 1.4))}>＋</button>
				<button class="rounded px-2 py-0.5 hover:bg-secondary" onclick={() => (zoom = Math.max(1, zoom / 1.4))}>－</button>
			</div>
		</div>

		{#if floors.length > 1}
			<div class="flex flex-wrap items-center gap-1 text-xs" role="tablist" aria-label="Floor">
				<span class="mr-1 text-muted-foreground">Floor</span>
				{#each floors as f (f.id)}
					<button role="tab" aria-selected={f.id === floorId}
						class="rounded-full px-3 py-1 ring-1 transition-colors {f.id === floorId
							? 'bg-primary/20 text-foreground ring-primary/40'
							: 'text-muted-foreground ring-border hover:bg-secondary'}"
						onclick={() => f.id !== floorId && onfloor(f.id)}>{f.name}</button>
				{/each}
			</div>
		{/if}

		<!-- legend: every chip shows how the layer is drawn and switches it on or off -->
		<div class="flex flex-wrap gap-1 text-xs">
			{#each legend as e (e.id)}
				<button aria-pressed={layers[e.id]} title={(layers[e.id] ? 'Hide ' : 'Show ') + e.label.toLowerCase()}
					class="flex items-center gap-1.5 rounded-full px-2.5 py-1 ring-1 ring-border transition-opacity hover:bg-secondary {layers[e.id] ? '' : 'opacity-40 line-through'}"
					onclick={() => flip(e.id)}>
					<svg viewBox="0 0 12 12" class="size-3 shrink-0" aria-hidden="true">
						{#if e.id === 'walls'}<rect x="1" y="1" width="10" height="10" rx="1" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8" />
						{:else if e.id === 'nogo'}<rect x="1" y="1" width="10" height="10" rx="1" fill={NOGO} fill-opacity="0.3" stroke={NOGO} />
						{:else if e.id === 'vwalls'}<line x1="1.5" y1="10.5" x2="10.5" y2="1.5" stroke={NOGO} stroke-width="2" stroke-linecap="round" />
						{:else if e.id === 'route'}<path d="M1 9 Q4 2 6 6 T11 3" fill="none" stroke="#fff" stroke-width="1.4" />
						{:else if e.id === 'dock'}<circle cx="6" cy="6" r="4" fill="#22c55e" stroke="#fff" stroke-width="1" />
						{:else if e.id === 'robot'}<circle cx="6" cy="6" r="4" fill="#38bdf8" stroke="#fff" stroke-width="1" />
						{:else}<text x="6" y="9.5" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor">A</text>{/if}
					</svg>
					{e.label}{#if e.count}<span class="text-muted-foreground">{e.count}</span>{/if}
				</button>
			{/each}
		</div>

		{#if splitting != null}
			<div class="flex items-center justify-between gap-2 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs">
				<span>{p1 ? 'Click the second point to cut' : 'Click the first point of the cut line'}</span>
				<button class="rounded px-2 py-0.5 hover:bg-secondary" onclick={cancelSplit}>Cancel</button>
			</div>
		{/if}

		<ContextMenu.Root>
			<ContextMenu.Trigger>
				{#snippet child({ props })}
					<div {...props} class="flex items-center justify-center overflow-auto rounded-lg bg-slate-900/60 p-2" style="height:min(70vh,560px)">
						<svg viewBox={`-2 -2 ${vec.width + 4} ${vec.height + 4}`} preserveAspectRatio="xMidYMid meet"
							style="width:100%;height:100%;display:block; cursor:{splitting != null ? 'crosshair' : 'default'}"
							shape-rendering="geometricPrecision">
							<g bind:this={gEl} transform={`translate(${(vec.width / 2) * (1 - zoom)},${(vec.height / 2) * (1 - zoom)}) scale(${zoom})`}>
								{#each vec.rooms as room (room.id)}
									{@const colour = PALETTE[(room.group ?? room.id) % PALETTE.length]}
									{@const isSel = selected.has(room.id)}
									{@const isHov = hovered === room.id}
									<path d={ringPath(room.rings)} fill={colour}
										fill-opacity={isSel ? 0.95 : isHov ? 0.75 : 0.5}
										stroke={isSel ? '#fff' : colour} stroke-width={isSel ? 1.4 : 0.5} stroke-linejoin="round"
										style="cursor:pointer;transition:fill-opacity .12s" role="button" tabindex="0" aria-label={room.name}
										onclick={() => toggle(room.id)}
										onkeydown={(e) => e.key === 'Enter' && toggle(room.id)}
										oncontextmenu={() => (ctxRoom = room)}
										onmouseenter={() => (hovered = room.id)}
										onmouseleave={() => (hovered = null)} />
								{/each}

								{#if layers.walls}
									<g fill="#0f172a" fill-opacity="0.85">
										{#each vec.walls as w}<rect x={w[0]} y={w[1]} width="1" height="1" />{/each}
									</g>
								{/if}
								<!-- the robot's own no-go zones and virtual walls (read-only) -->
								<g style="pointer-events:none">
									{#if layers.nogo}
										{#each vec.no_go_zones ?? [] as z}
											<polygon points={z.px.map((p: number[]) => p.join(',')).join(' ')}
												fill={NOGO} fill-opacity="0.22" stroke={NOGO} stroke-width="0.5" />
										{/each}
									{/if}
									{#if layers.vwalls}
										{#each vec.virtual_walls ?? [] as w}
											<line x1={w.px[0]} y1={w.px[1]} x2={w.px[2]} y2={w.px[3]}
												stroke={NOGO} stroke-width="1" stroke-linecap="round" />
										{/each}
									{/if}
								</g>

								{#if pathLine && layers.route}
									<path d={pathLine} fill="none" stroke="#fff" stroke-opacity="0.7" stroke-width="0.6" stroke-linejoin="round" />
								{/if}

								{#if vec.charger_px && layers.dock}
									<g transform={`translate(${vec.charger_px[0]},${vec.charger_px[1]})`}>
										<circle r="4" fill="#22c55e" fill-opacity="0.25" />
										<circle r="2" fill="#22c55e" stroke="#fff" stroke-width="0.5" />
									</g>
								{/if}
								{#if vec.robot_px && layers.robot}
									<g transform={`translate(${vec.robot_px[0]},${vec.robot_px[1]})`}>
										<circle r="5" fill="#38bdf8" fill-opacity="0.3" />
										<circle r="2.5" fill="#38bdf8" stroke="#fff" stroke-width="0.6" />
									</g>
								{/if}

								{#if layers.labels}
									{#each vec.rooms.filter((r) => (r.group ?? r.id) === r.id) as room (room.id)}
										<g transform={`translate(${room.centroid[0]},${room.centroid[1]})`} style="pointer-events:none">
											<text text-anchor="middle" font-size="6" font-weight="600" fill="#0b1220" stroke="#fff" stroke-width="1.6" paint-order="stroke">{room.name}</text>
											<text y="6" text-anchor="middle" font-size="4.4" fill="#0b1220" stroke="#fff" stroke-width="1.2" paint-order="stroke">{room.area_m2} m²</text>
										</g>
									{/each}
								{/if}

								<!-- split overlay: captures the two clicks + previews the cut -->
								{#if splitting != null}
									<rect x="-2" y="-2" width={vec.width + 4} height={vec.height + 4} fill="transparent"
										style="cursor:crosshair" onclick={splitClick}
										onmousemove={(e) => (cursor = toMap(e))} role="presentation" />
									{#if p1}
										<circle cx={p1[0]} cy={p1[1]} r="2" fill="#38bdf8" />
										{#if cursor}
											<line x1={p1[0]} y1={p1[1]} x2={cursor[0]} y2={cursor[1]} stroke="#38bdf8" stroke-width="1" stroke-dasharray="3 2" />
										{/if}
									{/if}
								{/if}
							</g>
						</svg>
					</div>
				{/snippet}
			</ContextMenu.Trigger>

			<ContextMenu.Portal>
				<ContextMenu.Content class="z-50 min-w-44 rounded-xl glass glass-strong p-1 text-sm shadow-2xl">
					<div class="px-2 py-1.5 text-xs text-muted-foreground">{ctxRoom?.name ?? 'Room'}</div>
					<ContextMenu.Item class="ctx-item" onSelect={() => ctxRoom && oncleanroom(ctxRoom.id)}>
						<Play class="size-4" /> Clean this room
					</ContextMenu.Item>
					<ContextMenu.Item class="ctx-item" onSelect={() => ctxRoom && onrename(ctxRoom.id)}>
						<Pencil class="size-4" /> Rename
					</ContextMenu.Item>
					<ContextMenu.Item class="ctx-item" onSelect={() => ctxRoom && startSplit(ctxRoom.id)}>
						<Scissors class="size-4" /> Split…
					</ContextMenu.Item>
					{#if selected.size >= 1}
						<ContextMenu.Item class="ctx-item" onSelect={() => ctxRoom && onmerge(ctxRoom.id)}>
							<Combine class="size-4" /> Merge with selection
						</ContextMenu.Item>
					{/if}
					{#if ctxRoom?.merged && !ctxRoom?.split_of}
						<ContextMenu.Item class="ctx-item" onSelect={() => ctxRoom && onunmerge(ctxRoom.id)}>
							<Ungroup class="size-4" /> Unmerge
						</ContextMenu.Item>
					{/if}
					{#if ctxRoom?.split}
						<ContextMenu.Item class="ctx-item" onSelect={() => ctxRoom && onunsplit(ctxRoom.split_of ?? ctxRoom.id)}>
							<Split class="size-4" /> Undo split
						</ContextMenu.Item>
					{/if}
				</ContextMenu.Content>
			</ContextMenu.Portal>
		</ContextMenu.Root>

		<p class="text-xs text-muted-foreground">
			Right-click a room to rename, split or merge it.
			{#if vec.route_info}
				The last position is where the last completed run ended ({vec.route_info.points} path points); the live position isn't available locally.
			{/if}
			No-go zones and virtual walls are the robot's own; change them in the Smart Life app.
		</p>
	</div>
{/if}

<style>
	:global(.ctx-item) {
		display: flex; align-items: center; gap: 0.6rem;
		padding: 0.5rem 0.65rem; border-radius: 0.6rem; cursor: pointer;
		color: var(--color-foreground); outline: none;
	}
	:global(.ctx-item[data-highlighted]) { background: hsl(210 40% 98% / 0.08); }
</style>
