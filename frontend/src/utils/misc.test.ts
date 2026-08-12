import { getCookie, parseErrorResponse } from './misc';

describe('parseErrorResponse', () => {
    it('handles a missing response', () => {
        expect(parseErrorResponse(null)).toBe('Unknown error occurred');
        expect(parseErrorResponse(undefined)).toBe('Unknown error occurred');
    });

    it('prefers the FastAPI detail field', () => {
        expect(parseErrorResponse({ status: 400, data: { detail: 'Bad thing' } }))
            .toBe('Bad thing');
    });

    it('falls back to statusText when there is no detail', () => {
        expect(parseErrorResponse({ status: 404, statusText: 'Not Found' }))
            .toBe('Not Found');
    });

    it('falls back to the status code when nothing else is present', () => {
        expect(parseErrorResponse({ status: 500 }))
            .toBe('HTTP error! status: 500');
    });
});

describe('getCookie', () => {
    afterEach(() => {
        // Clear cookies set during a test.
        document.cookie.split(';').forEach((c) => {
            const name = c.split('=')[0].trim();
            if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
        });
    });

    it('reads a named cookie value', () => {
        document.cookie = 'token=abc123';
        expect(getCookie('token')).toBe('abc123');
    });

    it('returns empty string for a missing cookie', () => {
        expect(getCookie('does_not_exist')).toBe('');
    });
});
