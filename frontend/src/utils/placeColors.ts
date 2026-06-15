// Stable colour per unique place, shared by DayNavBar and MapSearch so the same
// place is the same colour in both. Keyed by the place *name* (the only identity
// both views carry) — NOT by count/duration; duration is shown by the map's
// DensityLayer and the DayNav duration labels.

// Tableau 10 — calm, editorial categorical set.
const PLACE_PALETTE = [
    '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
    '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac',
];

const NO_PLACE = '#bdbdbd'; // grey for unknown / empty place

// djb2 hash → palette index. Deterministic, so a name always maps to one colour.
export function colorForPlace(name: string | null | undefined): string {
    if (!name) return NO_PLACE;
    let h = 5381;
    for (let i = 0; i < name.length; i++) {
        h = ((h << 5) + h + name.charCodeAt(i)) | 0;
    }
    return PLACE_PALETTE[Math.abs(h) % PLACE_PALETTE.length];
}

// Pick black or white text for legibility on a given background. Tableau's pale
// yellow/pink need dark text; the saturated hues need white. Uses W3C relative
// luminance with the standard 0.179 threshold.
export function textColorFor(hex: string): string {
    const m = hex.replace('#', '');
    const r = parseInt(m.slice(0, 2), 16) / 255;
    const g = parseInt(m.slice(2, 4), 16) / 255;
    const b = parseInt(m.slice(4, 6), 16) / 255;
    const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    return lum > 0.179 ? '#1a1a1a' : '#ffffff';
}

// Convenience: text colour for a place name in one call.
export function textColorForPlace(name: string | null | undefined): string {
    return textColorFor(colorForPlace(name));
}
