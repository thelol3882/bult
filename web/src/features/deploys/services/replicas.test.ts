import { describe, expect, it } from 'vitest';
import {
    formatReplicas,
    MAX_REPLICAS,
    scaleBlockedReason,
    scaleErrorMessage,
    stepReplicas,
} from './replicas';

describe('formatReplicas', () => {
    it('shows ready out of desired', () => {
        expect(formatReplicas(2, 3)).toBe('2/3');
        expect(formatReplicas(0, 1)).toBe('0/1');
    });
});

describe('stepReplicas', () => {
    it('stays inside 0..max', () => {
        expect(stepReplicas(0, -1)).toBe(0);
        expect(stepReplicas(MAX_REPLICAS, 1)).toBe(MAX_REPLICAS);
        expect(stepReplicas(2, 1)).toBe(3);
        expect(stepReplicas(2, -1)).toBe(1);
    });
});

describe('scaleBlockedReason', () => {
    it('blocks while the newest deploy is in progress', () => {
        for (const newestStatus of ['queued', 'building', 'starting'] as const) {
            expect(scaleBlockedReason({ newestStatus, current: 1, hasImageToStart: true })).toMatch(
                /in progress/,
            );
        }
    });

    it('blocks starting a stopped app that has no image', () => {
        expect(
            scaleBlockedReason({ newestStatus: 'failed', current: 0, hasImageToStart: false }),
        ).toMatch(/no image/);
    });

    it('allows a running app, and a stopped app with an image', () => {
        expect(
            scaleBlockedReason({ newestStatus: 'running', current: 2, hasImageToStart: false }),
        ).toBeUndefined();
        expect(
            scaleBlockedReason({ newestStatus: 'stopped', current: 0, hasImageToStart: true }),
        ).toBeUndefined();
    });
});

describe('scaleErrorMessage', () => {
    it('knows the codes a scale can fail with', () => {
        expect(scaleErrorMessage('no_node_available')).toMatch(/No node/);
        expect(scaleErrorMessage('nothing_to_start')).toMatch(/Deploy the app first/);
        expect(scaleErrorMessage('deploy_in_progress')).toMatch(/in progress/);
        expect(scaleErrorMessage('something_else')).toBeUndefined();
        expect(scaleErrorMessage(undefined)).toBeUndefined();
    });
});
