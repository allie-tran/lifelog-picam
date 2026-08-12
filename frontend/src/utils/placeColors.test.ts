import { colorForPlace, textColorFor, textColorForPlace } from './placeColors';

const NO_PLACE = '#bdbdbd';
const PALETTE = [
    '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
    '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac',
];

describe('colorForPlace', () => {
    it('returns the grey placeholder for empty names', () => {
        expect(colorForPlace(null)).toBe(NO_PLACE);
        expect(colorForPlace(undefined)).toBe(NO_PLACE);
        expect(colorForPlace('')).toBe(NO_PLACE);
    });

    it('is deterministic for the same name', () => {
        expect(colorForPlace('Dublin')).toBe(colorForPlace('Dublin'));
    });

    it('always maps into the palette', () => {
        for (const name of ['a', 'Dublin', 'WHSmith', 'Trinity College', 'x'.repeat(200)]) {
            expect(PALETTE).toContain(colorForPlace(name));
        }
    });
});

describe('textColorFor', () => {
    it('picks dark text on a light background', () => {
        expect(textColorFor('#edc948')).toBe('#1a1a1a'); // pale yellow
    });

    it('picks white text on a dark background', () => {
        expect(textColorFor('#000000')).toBe('#ffffff'); // black
        expect(textColorFor('#2c3e50')).toBe('#ffffff'); // dark slate
    });
});

describe('textColorForPlace', () => {
    it('composes colorForPlace and textColorFor', () => {
        expect(textColorForPlace('Dublin')).toBe(textColorFor(colorForPlace('Dublin')));
    });

    it('returns readable text for the unknown-place grey', () => {
        expect(textColorForPlace(null)).toBe(textColorFor(NO_PLACE));
    });
});
