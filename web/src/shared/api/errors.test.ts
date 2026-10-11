import { describe, expect, it } from 'vitest';
import { normalizeError } from './errors';

describe('normalizeError', () => {
    it('maps a 422 body error to a field error and strips the pydantic prefix', () => {
        const error = normalizeError({
            status: 422,
            data: {
                detail: [
                    {
                        loc: ['body', 'name'],
                        msg: "Value error, 'api' is a reserved platform name and cannot be used.",
                        type: 'value_error',
                    },
                    { loc: ['body', 'repo_url'], msg: 'Input should be a valid URL', type: 'x' },
                ],
            },
        });
        expect(error.status).toBe(422);
        expect(error.fieldErrors).toEqual({
            name: "'api' is a reserved platform name and cannot be used.",
            repo_url: 'Input should be a valid URL',
        });
    });

    it('passes a 409 detail through as the message', () => {
        expect(normalizeError({ status: 409, data: { detail: 'app name taken' } })).toEqual({
            status: 409,
            message: 'app name taken',
        });
    });

    it('passes a 503 JSON detail through (builder unavailable)', () => {
        expect(
            normalizeError({ status: 503, data: { detail: 'builder unavailable, try again' } }),
        ).toEqual({ status: 503, message: 'builder unavailable, try again' });
    });

    it('maps network failures and proxy 5xx without JSON to "API is unreachable"', () => {
        expect(normalizeError({ status: 'FETCH_ERROR', error: 'x' })).toEqual({
            status: 'network',
            message: 'API is unreachable',
        });
        expect(
            normalizeError({ status: 'PARSING_ERROR', originalStatus: 502, data: 'Bad' }).message,
        ).toBe('API is unreachable');
        expect(normalizeError(undefined).message).toBe('API is unreachable');
    });

    it('maps 500/502/503/504 without JSON to unreachable, other non-JSON 5xx to the status', () => {
        for (const originalStatus of [500, 502, 503, 504]) {
            expect(normalizeError({ status: 'PARSING_ERROR', originalStatus, data: '' })).toEqual({
                status: 'network',
                message: 'API is unreachable',
            });
        }
        expect(
            normalizeError({ status: 'PARSING_ERROR', originalStatus: 501, data: 'Nope' }),
        ).toEqual({ status: 501, message: 'Request failed (501)' });
    });

    it('falls back to the status code when there is no detail', () => {
        expect(normalizeError({ status: 500, data: {} }).message).toBe('Request failed (500)');
    });
});
