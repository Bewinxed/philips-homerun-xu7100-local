import { cubicOut, backOut } from 'svelte/easing';
import type { TransitionConfig } from 'svelte/transition';

// Materialize: a glass surface should read as a real material arriving — blur,
// scale and opacity animate together, with a hair of overshoot so it "grows
// toward" you rather than fading flatly (Apple: materialize, don't fade).
export function materialize(
	_node: Element,
	{ delay = 0, duration = 420, y = 10 }: { delay?: number; duration?: number; y?: number } = {}
): TransitionConfig {
	return {
		delay,
		duration,
		easing: backOut,
		css: (t) => {
			const u = 1 - cubicOut(t); // clamp blur/opacity to a non-overshooting curve
			const blur = Math.max(0, u * 7);
			const op = Math.min(1, cubicOut(t));
			return `opacity:${op}; filter: blur(${blur}px); transform: translateY(${u * y}px) scale(${0.96 + t * 0.04});`;
		}
	};
}

// Rise: lighter entrance for lists/tiles that stagger in under a section.
export function rise(
	_node: Element,
	{ delay = 0, duration = 460, y = 14 }: { delay?: number; duration?: number; y?: number } = {}
): TransitionConfig {
	return {
		delay,
		duration,
		easing: cubicOut,
		css: (t) => `opacity:${t}; transform: translateY(${(1 - t) * y}px);`
	};
}
