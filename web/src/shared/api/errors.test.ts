import { describe, expect, it } from 'vitest';
import { normalizeError } from './errors';

describe('normalizeError', () => {
    it('maps a 422 validation error to field errors from `fields`', () => {
        const error = normalizeError({
            status: 422,
            data: {
                detail: 'Invalid request',
                code: 'validation_error',
                trace_id: 'abc123',
                fields: {
                    name: "'api' is a reserved platform name and cannot be used.",
                    repo_url: 'Input should be a valid URL',
                },
            },
        });
        expect(error).toEqual({
            status: 422,
            message: 'Invalid request',
            code: 'validation_error',
            traceId: 'abc123',
            fieldErrors: {
                name: "'api' is a reserved platform name and cannot be used.",
                repo_url: 'Input should be a valid URL',
            },
        });
    });

    it('maps a single `field` to a field error and keeps the detail as the message', () => {
        const error = normalizeError({
            status: 409,
            data: {
                detail: "App with name 'blog' already exists.",
                code: 'app_name_taken',
                trace_id: 't1',
                field: 'name',
            },
        });
        expect(error.status).toBe(409);
        expect(error.code).toBe('app_name_taken');
        expect(error.message).toBe("App with name 'blog' already exists.");
        expect(error.fieldErrors).toEqual({ name: "App with name 'blog' already exists." });
    });

    it('passes a detail without code or fields through as the message', () => {
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
