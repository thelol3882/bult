import { describe, expect, it } from 'vitest';
import { mapAuthError } from './authErrors';

describe('mapAuthError', () => {
    it('shows invalid credentials as a general error', () => {
        const result = mapAuthError({
            status: 401,
            message: 'Invalid credentials',
            code: 'invalid_credentials',
        });
        expect(result).toEqual({ formError: 'Incorrect email or password' });
    });

    it('keeps field errors on their fields', () => {
        const result = mapAuthError({
            status: 409,
            message: 'Email already registered',
            code: 'email_taken',
            fieldErrors: { email: 'Email already registered' },
        });
        expect(result).toEqual({ fieldErrors: { email: 'Email already registered' } });
    });

    it('falls back to the message, and to a friendly one when offline', () => {
        expect(mapAuthError({ status: 500, message: 'Request failed (500)' })).toEqual({
            formError: 'Request failed (500)',
        });
        expect(
            mapAuthError({ status: 'network', message: 'API is unreachable' }).formError,
        ).toMatch(/Cannot reach/);
    });
});
