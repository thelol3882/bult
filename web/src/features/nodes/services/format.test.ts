import { describe, expect, it } from 'vitest';
import { formatMemory, lastSeenLabel, roleLabel, secondsSince } from './format';

const NOW = Date.parse('2026-10-18T12:00:00Z');

describe('lastSeenLabel', () => {
    it('counts seconds, then minutes, hours and days', () => {
        expect(lastSeenLabel('2026-10-18T11:59:57Z', NOW)).toBe('3 s ago');
        expect(lastSeenLabel('2026-10-18T11:58:00Z', NOW)).toBe('2 min ago');
        expect(lastSeenLabel('2026-10-18T09:00:00Z', NOW)).toBe('3 h ago');
        expect(lastSeenLabel('2026-10-14T12:00:00Z', NOW)).toBe('4 d ago');
    });

    it('treats a timestamp without an offset as UTC and never goes negative', () => {
        expect(secondsSince('2026-10-18T11:59:50', NOW)).toBe(10);
        expect(secondsSince('2026-10-18T12:00:05Z', NOW)).toBe(0);
    });
});

describe('formatMemory', () => {
    it('shows GiB, or a dash when unknown', () => {
        expect(formatMemory(2 * 1024 ** 3)).toBe('2.0 GiB');
        expect(formatMemory(0)).toBe('-');
    });
});

describe('roleLabel', () => {
    it('names every role', () => {
        expect(roleLabel('builder')).toBe('Builder');
        expect(roleLabel('both')).toBe('Builder + runner');
    });
});
