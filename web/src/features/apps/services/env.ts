import type { EnvMap } from '../types';

// Mirrors control-plane/app/apps/schemas/apps.py (EnvUpdate).
export const ENV_KEY_REGEX = /^[A-Z_][A-Z0-9_]*$/;
export const ENV_RESERVED_KEYS: ReadonlySet<string> = new Set(['PORT', 'FORWARDED_ALLOW_IPS']);
export const ENV_RESERVED_PREFIX = 'BULT_';
export const ENV_MAX_KEYS = 100;
export const ENV_MAX_KEY_LENGTH = 128;
export const ENV_MAX_VALUE_BYTES = 4096;

/** One line of the editor. Existing rows come from the API, which knows the key but not the value. */
export interface EnvRow {
    id: string;
    key: string;
    value: string;
    existing: boolean;
}

export const rowsFromKeys = (keys: string[]): EnvRow[] =>
    keys.map((key) => ({ id: `existing:${key}`, key, value: '', existing: true }));

export const rowsToEnv = (rows: EnvRow[]): EnvMap =>
    Object.fromEntries(rows.map((r) => [r.key, r.value]));

export function validateEnvKey(key: string): string | null {
    if (key.length === 0) return 'Name is required';
    if (key.length > ENV_MAX_KEY_LENGTH) return `At most ${ENV_MAX_KEY_LENGTH} characters`;
    if (!ENV_KEY_REGEX.test(key)) return 'Use A-Z, 0-9 and _, not starting with a digit';
    if (ENV_RESERVED_KEYS.has(key) || key.startsWith(ENV_RESERVED_PREFIX)) {
        return 'Reserved by the platform';
    }
    return null;
}

export function validateEnvValue(value: string): string | null {
    if (new TextEncoder().encode(value).length > ENV_MAX_VALUE_BYTES) {
        return `At most ${ENV_MAX_VALUE_BYTES} bytes`;
    }
    if (value.includes('\0')) return 'Must not contain a NUL character';
    return null;
}

/**
 * Errors keyed by form path (`rows.0.key`, `rows.0.value`, `rows`).
 * The map is replaced as a whole, so an existing variable needs its value typed again:
 * an empty value there would silently wipe it.
 */
export function validateEnvRows(rows: EnvRow[]): Record<string, string> {
    const errors: Record<string, string> = {};
    if (rows.length > ENV_MAX_KEYS) errors.rows = `At most ${ENV_MAX_KEYS} variables`;

    const seen = new Set<string>();
    rows.forEach((row, i) => {
        const keyError = validateEnvKey(row.key);
        if (keyError) errors[`rows.${i}.key`] = keyError;
        else if (seen.has(row.key)) errors[`rows.${i}.key`] = 'Duplicate name';
        seen.add(row.key);

        const valueError =
            row.existing && row.value === ''
                ? 'Enter the value again or remove the variable'
                : validateEnvValue(row.value);
        if (valueError) errors[`rows.${i}.value`] = valueError;
    });
    return errors;
}
