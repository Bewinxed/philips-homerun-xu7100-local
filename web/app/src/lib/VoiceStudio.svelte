<script lang="ts">
	import { onMount } from 'svelte';
	import { voice, type VoicePack, type VoiceLine, type VoiceJob, type VoiceSettings } from '$lib/api';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import {
		Play, Pause, Sparkles, Wand2, UploadCloud, KeyRound, Sliders, Search,
		Power, Settings2, Radar, Home, Trash2, Wrench, Download, RotateCcw,
		Lock, TriangleAlert, Moon, Locate, Loader2, Check, Volume2, RefreshCw
	} from '@lucide/svelte';

	let pack = $state<VoicePack | null>(null);
	let lines = $state<VoiceLine[]>([]);
	let settings = $state<VoiceSettings>({ voice_id: '', stability: 0.3, similarity_boost: 0.75, speed: 1.12 });
	let keySet = $state(true);
	let keyInput = $state('');
	let query = $state('');
	let filter = $state<string>('all');
	let showSettings = $state(false);
	let bust = $state(Date.now());

	// job / progress
	let job = $state<VoiceJob | null>(null);
	let jobNums = $state<Set<string>>(new Set()); // lines currently generating
	let installReport = $state<any>(null);

	// audio playback
	let audio: HTMLAudioElement | null = null;
	let playing = $state<string | null>(null);

	// tag insertion targets the last-focused textarea
	let focusedEl: HTMLTextAreaElement | null = null;
	let focusedNum = $state<string | null>(null);

	const CAT: Record<string, { icon: any; label: string; tint: string }> = {
		power: { icon: Power, label: 'Power', tint: 'text-sky-300' },
		setup: { icon: Settings2, label: 'Setup', tint: 'text-sky-300' },
		mapping: { icon: Radar, label: 'Mapping', tint: 'text-violet-300' },
		cleaning: { icon: Sparkles, label: 'Cleaning', tint: 'text-cyan-300' },
		localize: { icon: Locate, label: 'Locating', tint: 'text-violet-300' },
		docking: { icon: Home, label: 'Docking', tint: 'text-emerald-300' },
		empty: { icon: Trash2, label: 'Empty', tint: 'text-emerald-300' },
		maintenance: { icon: Wrench, label: 'Care', tint: 'text-amber-300' },
		update: { icon: Download, label: 'Update', tint: 'text-sky-300' },
		reset: { icon: RotateCcw, label: 'Reset', tint: 'text-slate-300' },
		child: { icon: Lock, label: 'Lock', tint: 'text-slate-300' },
		error: { icon: TriangleAlert, label: 'Alert', tint: 'text-rose-300' },
		sleep: { icon: Moon, label: 'Sleep', tint: 'text-slate-300' }
	};
	const cat = (c: string) => CAT[c] ?? CAT.error;

	const CATS = $derived([...new Set(lines.map((l) => l.category))]);
	const shown = $derived(
		lines.filter((l) => {
			if (filter !== 'all' && l.category !== filter) return false;
			if (query) {
				const q = query.toLowerCase();
				return l.event.toLowerCase().includes(q) || l.text.includes(query) || l.num.includes(q);
			}
			return true;
		})
	);
	const withAudio = $derived(lines.filter((l) => l.has_audio).length);

	async function load() {
		const p = await voice.pack();
		pack = p;
		lines = p.lines;
		settings = { ...p.settings };
		keySet = p.key_set;
		bust = Date.now();
	}
	onMount(load);

	// ---- editing -------------------------------------------------------------
	let saveTimers: Record<string, any> = {};
	function updateText(num: string, text: string) {
		const l = lines.find((x) => x.num === num);
		if (l) l.text = text;
		clearTimeout(saveTimers[num]);
		saveTimers[num] = setTimeout(() => voice.saveLine(num, text), 500);
	}
	async function saveNow(num: string) {
		const l = lines.find((x) => x.num === num);
		if (l) await voice.saveLine(num, l.text);
	}

	function insertTag(t: string) {
		const el = focusedEl;
		if (!el || !focusedNum) return;
		const num = focusedNum;
		const s = el.selectionStart ?? el.value.length;
		const e = el.selectionEnd ?? s;
		const chunk = `[${t}] `;
		const next = el.value.slice(0, s) + chunk + el.value.slice(e);
		updateText(num, next);
		requestAnimationFrame(() => {
			el.focus();
			const pos = s + chunk.length;
			el.setSelectionRange(pos, pos);
		});
	}

	// ---- settings ------------------------------------------------------------
	let setTimer: any;
	function pushSettings() {
		clearTimeout(setTimer);
		setTimer = setTimeout(() => voice.saveSettings(settings), 400);
	}

	async function saveKey() {
		if (!keyInput.trim()) return;
		const r = await voice.setKey(keyInput.trim());
		keySet = !!r.key_set;
		keyInput = '';
	}

	// ---- audio ---------------------------------------------------------------
	function togglePlay(num: string) {
		if (!audio) audio = new Audio();
		if (playing === num) {
			audio.pause();
			playing = null;
			return;
		}
		audio.src = voice.audioUrl(num, bust);
		audio.play().then(() => (playing = num)).catch(() => (playing = null));
		audio.onended = () => (playing = null);
	}

	// ---- jobs (generate / install) ------------------------------------------
	async function pollJob(jid: string, nums: string[]) {
		jobNums = new Set(nums);
		let done = false;
		while (!done) {
			await new Promise((r) => setTimeout(r, 800));
			try {
				const j = await voice.job(jid);
				job = j;
				done = j.state !== 'running';
			} catch {
				done = true;
			}
		}
		jobNums = new Set();
		await load(); // refresh audio timestamps + counts, bust cache
		if (job?.kind === 'install') installReport = job.report ?? null;
		setTimeout(() => {
			if (job?.state !== 'error') job = null;
		}, 2600);
	}

	async function genOne(num: string) {
		await saveNow(num);
		const r = await voice.generate([num]);
		if (r.ok) pollJob(r.job, [num]);
		else job = { id: '', kind: 'generate', state: 'error', total: 1, done: 0, items: [], error: r.error };
	}
	async function genAll() {
		// persist any pending edits first
		await Promise.all(lines.map((l) => voice.saveLine(l.num, l.text)));
		const r = await voice.generateAll();
		if (r.ok) pollJob(r.job, lines.map((l) => l.num));
		else job = { id: '', kind: 'generate', state: 'error', total: 0, done: 0, items: [], error: r.error };
	}
	async function installPack() {
		installReport = null;
		const r = await voice.install();
		if (r.ok) pollJob(r.job, []);
		else job = { id: '', kind: 'install', state: 'error', total: 0, done: 0, items: [], error: r.error };
	}

	const busy = $derived(!!job && job.state === 'running');
</script>

<div class="flex flex-col gap-5">
	<!-- studio header -->
	<div class="glass glass-strong p-5">
		<div class="flex flex-wrap items-start justify-between gap-4">
			<div class="flex items-start gap-3">
				<div class="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/15 text-primary">
					<Wand2 class="size-6" />
				</div>
				<div>
					<h2 class="text-lg font-semibold tracking-tight">Voice Studio</h2>
					<p class="max-w-prose text-sm text-muted-foreground">
						{pack?.character?.split('.')[0] ?? 'Edit the script, generate with ElevenLabs, push to the robot.'}
					</p>
					<div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
						<Badge variant="secondary">{withAudio}/{lines.length} voiced</Badge>
						{#if keySet}
							<span class="flex items-center gap-1 text-emerald-400"><Check class="size-3.5" /> ElevenLabs key set</span>
						{:else}
							<span class="flex items-center gap-1 text-amber-400"><KeyRound class="size-3.5" /> no API key</span>
						{/if}
					</div>
				</div>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				<Button variant="secondary" size="sm" onclick={() => (showSettings = !showSettings)}>
					<Sliders class="size-4" /> Voice
				</Button>
				<Button variant="secondary" size="sm" onclick={genAll} disabled={busy || !keySet}>
					<Sparkles class="size-4" /> Generate all
				</Button>
				<Button size="sm" onclick={installPack} disabled={busy}>
					<UploadCloud class="size-4" /> Install to robot
				</Button>
			</div>
		</div>

		{#if !keySet}
			<div class="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
				<KeyRound class="size-4 text-amber-400" />
				<span class="text-sm text-muted-foreground">Paste your ElevenLabs API key (stored locally, never leaves this machine):</span>
				<input type="password" bind:value={keyInput} placeholder="sk_…"
					class="min-w-48 flex-1 rounded-md border border-input bg-background/60 px-2 py-1 text-sm" />
				<Button size="sm" onclick={saveKey}>Save</Button>
			</div>
		{/if}

		{#if showSettings}
			<div class="mt-4 grid gap-4 rounded-xl border border-border/60 bg-background/30 p-4 sm:grid-cols-2 lg:grid-cols-4">
				<label class="flex flex-col gap-1 text-sm">
					<span class="text-muted-foreground">Voice ID</span>
					<input bind:value={settings.voice_id} oninput={pushSettings}
						class="rounded-md border border-input bg-background/60 px-2 py-1 font-mono text-xs" />
				</label>
				<label class="flex flex-col gap-1 text-sm">
					<span class="flex justify-between text-muted-foreground">Stability <span class="font-mono text-foreground">{(+settings.stability).toFixed(2)}</span></span>
					<input type="range" min="0" max="1" step="0.05" bind:value={settings.stability} oninput={pushSettings} />
					<span class="text-xs text-muted-foreground/70">low = more expressive</span>
				</label>
				<label class="flex flex-col gap-1 text-sm">
					<span class="flex justify-between text-muted-foreground">Similarity <span class="font-mono text-foreground">{(+settings.similarity_boost).toFixed(2)}</span></span>
					<input type="range" min="0" max="1" step="0.05" bind:value={settings.similarity_boost} oninput={pushSettings} />
					<span class="text-xs text-muted-foreground/70">stays close to the voice</span>
				</label>
				<label class="flex flex-col gap-1 text-sm">
					<span class="flex justify-between text-muted-foreground">Speed <span class="font-mono text-foreground">{(+settings.speed).toFixed(2)}×</span></span>
					<input type="range" min="0.85" max="1.4" step="0.01" bind:value={settings.speed} oninput={pushSettings} />
					<span class="text-xs text-muted-foreground/70">grumpy reads sharp &amp; quick</span>
				</label>
			</div>
		{/if}
	</div>

	<!-- filter bar -->
	<div class="flex flex-wrap items-center gap-2">
		<div class="glass flex items-center gap-2 px-3 py-1.5">
			<Search class="size-4 text-muted-foreground" />
			<input bind:value={query} placeholder="Search prompts…"
				class="w-40 bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
		</div>
		<button class="rounded-full px-3 py-1.5 text-sm font-medium transition
			{filter === 'all' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'}"
			onclick={() => (filter = 'all')}>All</button>
		{#each CATS as c}
			{@const C = cat(c)}
			<button class="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition
				{filter === c ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'}"
				onclick={() => (filter = c)}>
				<C.icon class="size-3.5" /> {C.label}
			</button>
		{/each}
	</div>

	<!-- prompt rows -->
	<div class="flex flex-col gap-3">
		{#each shown as line (line.num)}
			{@const C = cat(line.category)}
			{@const gen = jobNums.has(line.num)}
			<div class="glass glass-hover p-4">
				<div class="flex flex-col gap-3 lg:flex-row lg:items-stretch">
					<!-- meta -->
					<div class="flex shrink-0 items-center gap-3 lg:w-52 lg:flex-col lg:items-start">
						<div class="grid size-9 place-items-center rounded-lg bg-white/5 {C.tint}">
							<C.icon class="size-5" />
						</div>
						<div class="min-w-0">
							<div class="flex items-center gap-2">
								<span class="font-mono text-xs text-muted-foreground">#{line.num}</span>
								{#if line.has_audio}
									<span class="size-1.5 rounded-full bg-emerald-400" title="voiced"></span>
								{:else}
									<span class="size-1.5 rounded-full bg-amber-400" title="no audio yet"></span>
								{/if}
							</div>
							<p class="truncate text-sm font-medium">{line.event}</p>
						</div>
					</div>

					<!-- editor -->
					<div class="flex min-w-0 flex-1 flex-col gap-2">
						<textarea
							class="rtl min-h-16 w-full resize-y rounded-lg border border-input bg-background/50 px-3 py-2 outline-none transition focus:border-primary/60"
							value={line.text}
							placeholder="اكتب النص هنا…"
							oninput={(e) => updateText(line.num, (e.currentTarget as HTMLTextAreaElement).value)}
							onblur={() => saveNow(line.num)}
							onfocus={(e) => { focusedEl = e.currentTarget as HTMLTextAreaElement; focusedNum = line.num; }}
						></textarea>

						<!-- quick tag palette (grumpy set) + full set -->
						{#if focusedNum === line.num && pack}
							<div class="flex flex-wrap items-center gap-1.5">
								<span class="text-xs text-muted-foreground">Tags:</span>
								{#each pack.tag_groups as grp}
									{#each grp.tags as tag}
										<button
											onmousedown={(e) => { e.preventDefault(); insertTag(tag.t); }}
											class="rounded-md px-2 py-0.5 text-xs transition
												{tag.grumpy ? 'bg-primary/15 text-primary hover:bg-primary/25' : 'bg-white/5 text-muted-foreground hover:bg-white/10'}">
											{tag.t}
										</button>
									{/each}
								{/each}
							</div>
						{/if}
					</div>

					<!-- actions -->
					<div class="flex shrink-0 items-center gap-2 lg:flex-col lg:justify-center">
						<Button size="sm" variant="secondary" class="w-full"
							onclick={() => togglePlay(line.num)} disabled={!line.has_audio}>
							{#if playing === line.num}<Pause class="size-4" />{:else}<Play class="size-4" />{/if}
							Play
						</Button>
						<Button size="sm" class="w-full" onclick={() => genOne(line.num)} disabled={busy || !keySet || !line.text.trim()}>
							{#if gen}<Loader2 class="size-4 animate-spin" />{:else}<Sparkles class="size-4" />{/if}
							{gen ? 'Generating' : 'Regenerate'}
						</Button>
					</div>
				</div>
			</div>
		{/each}
		{#if !shown.length}
			<div class="glass grid place-items-center p-10 text-sm text-muted-foreground">No prompts match.</div>
		{/if}
	</div>
</div>

<!-- job progress toast -->
{#if job}
	<div class="fixed inset-x-0 bottom-4 z-50 mx-auto flex max-w-md items-center gap-3 rounded-2xl glass glass-strong px-4 py-3 shadow-2xl">
		{#if job.state === 'running'}
			<Loader2 class="size-5 shrink-0 animate-spin text-primary" />
		{:else if job.state === 'error'}
			<TriangleAlert class="size-5 shrink-0 text-rose-400" />
		{:else}
			<Check class="size-5 shrink-0 text-emerald-400" />
		{/if}
		<div class="min-w-0 flex-1">
			<p class="text-sm font-medium">
				{#if job.kind === 'install'}
					{job.state === 'running' ? 'Pushing pack to the robot…' : job.state === 'error' ? 'Install failed' : 'Installed on the robot'}
				{:else}
					{job.state === 'running' ? `Generating ${job.done}/${job.total}…` : job.state === 'error' ? 'Generation failed' : `Generated ${job.total} line${job.total === 1 ? '' : 's'}`}
				{/if}
			</p>
			{#if job.error}<p class="truncate text-xs text-rose-300">{job.error}</p>{/if}
			{#if job.kind === 'generate' && job.total > 1}
				<div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/10">
					<div class="h-full rounded-full bg-primary transition-all" style="width:{(100 * job.done) / Math.max(1, job.total)}%"></div>
				</div>
			{/if}
		</div>
		<button class="text-xs text-muted-foreground hover:text-foreground" onclick={() => (job = null)}>Dismiss</button>
	</div>
{/if}
