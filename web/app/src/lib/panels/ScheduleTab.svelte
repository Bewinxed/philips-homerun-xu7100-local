<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { rise } from '$lib/transitions';
	import Switch from '$lib/components/Switch.svelte';
	import { schedules as api, type Schedule } from '$lib/api';
	import { CalendarClock, Plus, Trash2 } from '@lucide/svelte';

	// Monday first, like the app (and the robot's day bits)
	const DAYS: [string, string][] = [['mon', 'Mo'], ['tue', 'Tu'], ['wed', 'We'], ['thu', 'Th'], ['fri', 'Fr'], ['sat', 'Sa'], ['sun', 'Su']];

	let list = $state<Schedule[] | null>(null);
	let max = $state(8);
	let busy = $state<number | 'add' | null>(null);
	let newTime = $state('09:00');
	let newDays = $state<string[]>(['mon', 'tue', 'wed', 'thu', 'fri']);
	// the app's "Schoonmaakmethode"; new schedules start like the app's: vacuum, strong, 1x
	type Setting = 'mode' | 'suction' | 'water' | 'repeat';
	const SETTINGS: { key: Setting; label: string; options: [string, string][] }[] = [
		{ key: 'mode', label: 'Mode', options: [['both_work', 'Vacuum + mop'], ['only_sweep', 'Vacuum'], ['only_mop', 'Mop'], ['intensive', 'Intensive'], ['quiet', 'Quiet']] },
		{ key: 'suction', label: 'Suction', options: [['closed', 'Off'], ['gentle', 'Gentle'], ['normal', 'Normal'], ['strong', 'Strong'], ['max', 'Max']] },
		{ key: 'water', label: 'Water', options: [['closed', 'Off'], ['low', 'Low'], ['middle', 'Medium'], ['high', 'High']] },
		{ key: 'repeat', label: 'Repeat', options: [['1', '1x'], ['2', '2x'], ['5', '5x']] }
	];
	let newSettings = $state<Record<Setting, string>>({ mode: 'only_sweep', suction: 'strong', water: 'closed', repeat: '1' });
	const settingValue = (key: Setting, v: string) => (key === 'repeat' ? Number(v) : v);

	async function load() {
		try { const r = await api.list(); list = r.schedules; max = r.max ?? 8; } catch { list = []; }
	}
	async function run(key: number | 'add', p: Promise<{ ok: boolean; error?: string; schedules?: Schedule[] }>, done: string) {
		busy = key;
		const r = await p.catch(() => ({ ok: false, error: 'backend unreachable' }) as { ok: boolean; error?: string; schedules?: Schedule[] });
		busy = null;
		if (r.ok && r.schedules) { list = r.schedules; toast.success(done); }
		else { toast.error(r.error ?? 'Not saved'); await load(); }
	}
	const edit = (s: Schedule, patch: Partial<Schedule>) => run(s.index, api.edit(s.index, patch), 'Schedule saved on the robot');
	const toggleDay = (s: Schedule, d: string) =>
		edit(s, { days: s.days.includes(d) ? s.days.filter((x) => x !== d) : [...s.days, d] });
	const add = () => run('add', api.add({
		time: newTime, days: newDays, enabled: true, mode: newSettings.mode, suction: newSettings.suction,
		water: newSettings.water, repeat: Number(newSettings.repeat)
	}), 'Schedule added');
	const remove = (s: Schedule) => run(s.index, api.remove(s.index), 'Schedule deleted');
	const label = (s: Schedule) => s.days.length === 7 ? 'Every day'
		: s.days.length === 0 ? 'Once' : DAYS.filter(([d]) => s.days.includes(d)).map(([, l]) => l).join(' ');

	onMount(load);
</script>

<section class="glass p-5" in:rise={{ delay: 60 }}>
	<div class="mb-4 flex items-center gap-2">
		<CalendarClock class="size-5 text-primary" />
		<h2 class="text-lg font-semibold">Schedule</h2>
		<span class="ml-auto text-xs text-muted-foreground">Cleans the whole floor the robot is on, like the app</span>
	</div>

	{#if list === null}
		<p class="text-sm text-muted-foreground">Loading…</p>
	{:else}
		{#if !list.length}<p class="mb-3 text-sm text-muted-foreground">No schedules yet.</p>{/if}
		<div class="flex flex-col gap-3">
			{#each list as s (s.index)}
				<div class="flex flex-wrap items-center gap-3 rounded-xl bg-secondary/40 px-3 py-2.5 {busy === s.index ? 'opacity-60' : ''}">
					<Switch checked={s.enabled} onchange={(v) => edit(s, { enabled: v })} />
					<input type="time" value={s.time} disabled={busy !== null}
						class="rounded-md bg-background/60 px-2 py-1 text-base tabular-nums ring-1 ring-border"
						onchange={(e) => edit(s, { time: (e.target as HTMLInputElement).value })} />
					<div class="flex gap-1">
						{#each DAYS as [d, l]}
							<button class="size-8 rounded-full text-xs ring-1 transition-colors {s.days.includes(d) ? 'bg-primary/25 ring-primary/50' : 'text-muted-foreground ring-border hover:bg-secondary'}"
								disabled={busy !== null} onclick={() => toggleDay(s, d)}>{l}</button>
						{/each}
					</div>
					<span class="text-xs text-muted-foreground">{label(s)}{s.other_map ? ' · another map' : ''}{s.whole_floor ? '' : ` · rooms ${s.rooms.join(', ')}`}</span>
					<button class="ml-auto rounded-full p-2 text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Delete schedule"
						disabled={busy !== null} onclick={() => remove(s)}><Trash2 class="size-4" /></button>
					<div class="flex w-full flex-wrap gap-2">
						{#each SETTINGS as set}
							<label class="flex items-center gap-1.5 text-xs text-muted-foreground">{set.label}
								<select class="rounded-md bg-background/60 px-1.5 py-1 text-sm text-foreground ring-1 ring-border"
									value={s[set.key] == null ? '' : String(s[set.key])} disabled={busy !== null}
									onchange={(e) => edit(s, { [set.key]: settingValue(set.key, (e.target as HTMLSelectElement).value) })}>
									{#if s[set.key] == null}<option value="">?</option>{/if}
									{#each set.options as [v, l]}<option value={v}>{l}</option>{/each}
								</select>
							</label>
						{/each}
					</div>
				</div>
			{/each}
		</div>

		{#if list.length < max}
			<div class="mt-4 flex flex-wrap items-center gap-3 border-t border-border/60 pt-4">
				<input type="time" bind:value={newTime} class="rounded-md bg-background/60 px-2 py-1 text-base tabular-nums ring-1 ring-border" />
				<div class="flex gap-1">
					{#each DAYS as [d, l]}
						<button class="size-8 rounded-full text-xs ring-1 transition-colors {newDays.includes(d) ? 'bg-primary/25 ring-primary/50' : 'text-muted-foreground ring-border hover:bg-secondary'}"
							onclick={() => (newDays = newDays.includes(d) ? newDays.filter((x) => x !== d) : [...newDays, d])}>{l}</button>
					{/each}
				</div>
				<div class="flex w-full flex-wrap gap-2">
					{#each SETTINGS as set}
						<label class="flex items-center gap-1.5 text-xs text-muted-foreground">{set.label}
							<select class="rounded-md bg-background/60 px-1.5 py-1 text-sm text-foreground ring-1 ring-border" bind:value={newSettings[set.key]}>
								{#each set.options as [v, l]}<option value={v}>{l}</option>{/each}
							</select>
						</label>
					{/each}
				</div>
				<button class="ml-auto flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
					disabled={busy !== null} onclick={add}><Plus class="size-4" /> {busy === 'add' ? 'Adding…' : 'Add schedule'}</button>
			</div>
		{/if}
	{/if}
</section>
