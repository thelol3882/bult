import { describe, expect, it } from 'vitest';
import { isDeployActive, isDeployCancellable, isDeployFinished, type DeployStatus } from './index';

describe('deploy status helpers', () => {
    it('treats queued, building and starting as active and keeps polling them', () => {
        for (const status of ['queued', 'building', 'starting'] as DeployStatus[]) {
            expect(isDeployActive(status)).toBe(true);
            expect(isDeployFinished(status)).toBe(false);
        }
    });

    it('treats running, failed, cancelled, superseded and stopped as finished', () => {
        const finished = ['running', 'failed', 'cancelled', 'superseded', 'stopped'];
        for (const status of finished as DeployStatus[]) {
            expect(isDeployActive(status)).toBe(false);
            expect(isDeployFinished(status)).toBe(true);
        }
    });

    it('lets the user cancel only a queued or building deploy', () => {
        expect(isDeployCancellable('queued')).toBe(true);
        expect(isDeployCancellable('building')).toBe(true);
        for (const status of ['starting', 'running', 'failed', 'cancelled'] as DeployStatus[]) {
            expect(isDeployCancellable(status)).toBe(false);
        }
    });
});
