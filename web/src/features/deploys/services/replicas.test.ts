import { describe, expect, it } from 'vitest';
import type { DeployReplica } from '../types';
import {
    formatReplicas,
    hasFailureDetails,
    isDegraded,
    MAX_REPLICAS,
    REPLICA_STATUS,
    replicaHint,
    retryLabel,
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

const replica = (over: Partial<DeployReplica> = {}): DeployReplica => ({
    index: 0,
    node: 'bult-node-1',
    host_port: 20001,
    status: 'running',
    exit_code: null,
    recent_failures: 0,
    reason: '',
    log_tail: [],
    retry_at: null,
    ...over,
});

describe('REPLICA_STATUS', () => {
    it('gives every status its own label and color', () => {
        const all = Object.values(REPLICA_STATUS);
        expect(all).toHaveLength(6);
        expect(new Set(all.map((m) => m.label)).size).toBe(6);
        expect(new Set(all.map((m) => m.color)).size).toBe(6);
    });
});

describe('retryLabel', () => {
    const now = Date.parse('2026-10-21T10:00:00Z');

    it('counts down to the retry', () => {
        expect(retryLabel('2026-10-21T10:00:20Z', now)).toBe('restarting in 20 s');
        expect(retryLabel('2026-10-21T10:02:10Z', now)).toBe('restarting in 3 min');
    });

    it('treats a timestamp without an offset as UTC', () => {
        expect(retryLabel('2026-10-21T10:00:05', now)).toBe('restarting in 5 s');
    });

    it('says nothing without a retry or once its time has passed', () => {
        expect(retryLabel(null, now)).toBeNull();
        expect(retryLabel('2026-10-21T09:59:59Z', now)).toBeNull();
        expect(retryLabel('2026-10-21T10:00:00Z', now)).toBeNull();
    });
});

describe('replicaHint', () => {
    it('prefers the reason from the API, else the generic hint', () => {
        expect(replicaHint(replica({ status: 'exited', reason: 'exited with code 1' }))).toBe(
            'exited with code 1',
        );
        expect(replicaHint(replica({ status: 'lost' }))).toBe(REPLICA_STATUS.lost.hint);
        expect(replicaHint(replica())).toBe('');
    });
});

describe('hasFailureDetails', () => {
    it('always for a crash loop', () => {
        expect(hasFailureDetails(replica({ status: 'crashloop' }))).toBe(true);
    });

    it('for exited and oom only when there is output', () => {
        for (const status of ['exited', 'oom'] as const) {
            expect(hasFailureDetails(replica({ status }))).toBe(false);
            expect(hasFailureDetails(replica({ status, log_tail: ['boom'] }))).toBe(true);
        }
    });

    it('never for the other statuses', () => {
        for (const status of ['running', 'unhealthy', 'lost'] as const) {
            expect(hasFailureDetails(replica({ status, log_tail: ['x'] }))).toBe(false);
        }
    });
});

describe('isDegraded', () => {
    it('flags ready below desired', () => {
        expect(isDegraded(1, 2)).toBe(true);
        expect(isDegraded(2, 2)).toBe(false);
    });
});
