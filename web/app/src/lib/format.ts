// Turn every raw robot value/key into human language. Nothing with an
// underscore or a protocol enum should ever reach the screen.

const VALUES: Record<string, string> = {
	// suction
	quiet: 'Quiet', gentle: 'Gentle', normal: 'Normal', standard: 'Normal',
	strong: 'Strong', max: 'Max', turbo: 'Max',
	// water
	low: 'Low', middle: 'Medium', high: 'High', closed: 'Off', close: 'Off',
	// mop / components
	installed: 'Installed', removed: 'Removed', uninstalled: 'Removed',
	// clean type
	vacuum_without_mopping: 'Vacuum only',
	vacuum_and_mopping: 'Vacuum + mop',
	vacuum_with_mopping: 'Vacuum + mop',
	mopping_only: 'Mop only', mop_only: 'Mop only', sweep_only: 'Vacuum only',
	// work mode
	both_work: 'Vacuum + mop', vacuum_work: 'Vacuum', mop_work: 'Mop',
	sweep_work: 'Vacuum',
	// modes / status
	smart: 'Smart clean', part: 'Room clean', zone: 'Zone clean', pose: 'Go-to',
	spot: 'Spot', standby: 'Standby', chargego: 'Returning', charge: 'Charging',
	both: 'Vacuum + mop'
};

const titleCase = (s: string) =>
	s.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
		.replace(/\b\w/g, (c) => c.toUpperCase());

export const humanize = (v: unknown): string => {
	if (v === null || v === undefined || v === '') return '—';
	if (typeof v === 'boolean') return v ? 'On' : 'Off';
	const key = String(v).toLowerCase();
	return VALUES[key] ?? titleCase(String(v));
};

// Friendly durations: minutes -> "25 h 22 m" / "45 m"
export const dur = (min: number): string => {
	min = Math.round(min || 0);
	if (min < 60) return `${min} min`;
	const h = Math.floor(min / 60);
	const m = min % 60;
	return m ? `${h} h ${m} m` : `${h} h`;
};

// Compact hours for consumables: "142 h left" -> keep, but round nicely
export const hoursLeft = (h: number): string => {
	if (h >= 100) return `${Math.round(h)} h`;
	return `${h.toFixed(0)} h`;
};

export const area = (m2: number): string => `${Math.round(m2 || 0)} m²`;
