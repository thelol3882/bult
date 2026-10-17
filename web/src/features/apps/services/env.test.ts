import { describe, expect, it } from 'vitest';
import {
    ENV_MAX_KEYS,
    rowsFromKeys,
    rowsToEnv,
    validateEnvKey,
    validateEnvRows,
    validateEnvValue,
    type EnvRow,
} from './env';

const row = (key: string, value: string, existing = false): EnvRow => ({
    id: key,
    key,
    value,
    existing,
});

describe('validateEnvKey', () => {
    it('accepts upper-case names', () => {
        for (const key of ['DB_URL', '_X', 'A1']) expect(validateEnvKey(key)).toBeNull();
    });

    it('rejects bad and reserved names like the API does', () => {
        for (const key of ['', 'lower', '1A', 'A-B', 'PORT', 'FORWARDED_ALLOW_IPS', 'BULT_X']) {
            expect(validateEnvKey(key)).not.toBeNull();
        }
    });
});

describe('validateEnvValue', () => {
    it('counts bytes, not characters', () => {
        expect(validateEnvValue('x'.repeat(4096))).toBeNull();
        expect(validateEnvValue('x'.repeat(4097))).not.toBeNull();
        expect(validateEnvValue('é'.repeat(2049))).not.toBeNull();
    });

    it('rejects NUL', () => {
        expect(validateEnvValue('a\0b')).not.toBeNull();
    });
});

describe('validateEnvRows', () => {
    it('refuses to save an existing variable without its value (it would be wiped)', () => {
        const errors = validateEnvRows([row('API_KEY', '', true), row('NEW', '', false)]);

        expect(errors['rows.0.value']).toBeDefined();
        expect(errors['rows.1.value']).toBeUndefined(); // a new variable may be empty
    });

    it('flags duplicates and too many rows', () => {
        expect(validateEnvRows([row('A', '1'), row('A', '2')])['rows.1.key']).toBe(
            'Duplicate name',
        );

        const many = Array.from({ length: ENV_MAX_KEYS + 1 }, (_, i) => row(`V_${i}`, 'v'));
        expect(validateEnvRows(many).rows).toBeDefined();
    });

    it('passes a valid set', () => {
        expect(validateEnvRows([row('A', '1', true), row('B', '')])).toEqual({});
    });
});

describe('rows <-> env', () => {
    it('starts from the keys with empty values', () => {
        const rows = rowsFromKeys(['A', 'B']);

        expect(rows.map((r) => [r.key, r.value, r.existing])).toEqual([
            ['A', '', true],
            ['B', '', true],
        ]);
    });

    it('sends the full map', () => {
        expect(rowsToEnv([row('A', '1'), row('B', '2')])).toEqual({ A: '1', B: '2' });
    });
});
