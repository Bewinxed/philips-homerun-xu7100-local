export type RobotState = {
	source: 'robot' | 'sim';
	connected: boolean;
	state: 'idle' | 'cleaning' | 'paused' | 'returning' | 'docked' | 'charging' | 'error';
	battery: number | null;
	fan: string | null;
	water: string | null;
	mode: string | null;
	clean_area: number | null;
	clean_time: number | null;
	fault: unknown;
	raw: Record<string, unknown>;
	last_update: number;
};

export type MapMeta = {
	ok: boolean;
	error?: string;
	width?: number;
	height?: number;
	resolution_mm?: number;
	charger?: [number, number];
	robot?: [number, number];
	rooms?: { id: number; name: string }[];
	path_points?: number;
	ts?: number;
};

const j = (b: unknown) => ({
	method: 'POST',
	headers: { 'content-type': 'application/json' },
	body: JSON.stringify(b)
});

export const api = {
	state: () => fetch('/api/state').then((r) => r.json() as Promise<RobotState>),
	command: (action: string) => fetch('/api/command', j({ action })).then((r) => r.json()),
	fan: (level: string) => fetch('/api/fan', j({ level })).then((r) => r.json()),
	water: (level: string) => fetch('/api/water', j({ level })).then((r) => r.json()),
	mapMeta: (force = false) =>
		fetch('/api/map/meta' + (force ? '?force=1' : '')).then((r) => r.json() as Promise<MapMeta>)
};

export type Diagnostics = {
	consumables: { name: string; remaining_min: number; full_min: number; percent: number; hours_left: number }[];
	faults: string[];
	fault_code?: number;
	totals: Record<string, { value: number; unit: string }>;
	device: Record<string, string>;
	components: Record<string, string>;
	toggles?: Record<string, { label: string; on: boolean }>;
	settings?: Record<string, number>;
};

export const diagnostics = () => fetch('/api/diagnostics').then((r) => r.json() as Promise<Diagnostics>);

const post = (url: string, b: unknown) =>
	fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(b) })
		.then((r) => r.json());

export const startMapping = () => post('/api/mapping', {});
export const drive = (direction: string) => post('/api/drive', { direction });
export const toggle = (name: string, on: boolean) => post('/api/toggle', { name, on });
export const setVolume = (level: number) => post('/api/volume', { level });
export const resetConsumable = (which: string) => post('/api/reset-consumable', { which });
export const gotoPoint = (x: number, y: number) => post('/api/goto', { x, y });

export const mapVector = (force = false) =>
	fetch('/api/map/vector' + (force ? '?force=1' : '')).then((r) => r.json());
export const cleanRooms = (rooms: number[], passes = 1) => post('/api/rooms/clean', { rooms, passes });
export const renameRoom = (id: number, name: string) => post('/api/rooms/rename', { id, name });
export const mergeRooms = (a: number, b: number) => post('/api/rooms/merge', { a, b });
export const unmergeRoom = (id: number) => post('/api/rooms/unmerge', { id });
export const splitRoom = (id: number, x1: number, y1: number, x2: number, y2: number) =>
	post('/api/rooms/split', { id, x1, y1, x2, y2 });
export const unsplitRoom = (id: number) => post('/api/rooms/unsplit', { id });
export const roomAttrs = (id: number, fan?: string, water?: string, passes?: number) =>
	post('/api/rooms/attrs', { id, fan, water, passes });

export const LANGUAGES = ['english','german','french','russian','spanish','italian',
	'portuguese','korean','japanese','latin','chinese_simplified','chinese_traditional'];
export const setLanguage = (language: string) => post('/api/language', { language });

export const emptyBin = () => post('/api/empty', {});

// ---- Voice Studio ----------------------------------------------------------
export type VoiceLine = {
	num: string;
	event: string;
	category: string;
	text: string;
	edited: boolean;
	has_audio: boolean;
	audio_at: number | null;
	bytes: number;
	stale: boolean;
};
export type VoiceTag = { t: string; grumpy?: boolean };
export type VoiceSettings = {
	voice_id: string;
	stability: number;
	similarity_boost: number;
	speed: number;
};
export type VoicePack = {
	character: string;
	settings: VoiceSettings;
	tag_groups: { name: string; tags: VoiceTag[] }[];
	voice_id_default: string;
	key_set: boolean;
	lines: VoiceLine[];
	count: number;
	with_audio: number;
};
export type VoiceJob = {
	id: string;
	kind: 'generate' | 'install';
	state: 'running' | 'done' | 'error';
	total: number;
	done: number;
	items: { num: string; state: string; error: string | null }[];
	error: string | null;
	report?: unknown;
};

export const voice = {
	pack: () => fetch('/api/voice/pack').then((r) => r.json() as Promise<VoicePack>),
	saveLine: (num: string, text: string) => post('/api/voice/line', { num, text }),
	saveSettings: (s: Partial<VoiceSettings>) => post('/api/voice/settings', s),
	setKey: (key: string) => post('/api/voice/key', { key }),
	generate: (nums: string[]) => post('/api/voice/generate', { nums }),
	generateAll: () => post('/api/voice/generate', { all: true }),
	install: () => post('/api/voice/install', {}),
	job: (jid: string) => fetch('/api/voice/job/' + jid).then((r) => r.json() as Promise<VoiceJob>),
	audioUrl: (num: string, bust: number | null) => `/api/voice/audio/${num}?t=${bust ?? 0}`
};
