import { describe, expect, it } from 'vitest';
import { isDeployActive, isDeployFinished, type DeployStatus } from './index';

describe('deploy status helpers', () => {
    it('treats queued, building and starting as active and keeps polling them', () => {
        for (const status of ['queued', 'building', 'starting'] as DeployStatus[]) {
            expect(isDeployActive(status)).toBe(true);
            expect(isDeployFinished(status)).toBe(false);
        }
    });

    it('treats running and failed as finished', () => {
        for (const status of ['running', 'failed'] as DeployStatus[]) {
            expect(isDeployActive(status)).toBe(false);
            expect(isDeployFinished(status)).toBe(true);
        }
    });
});
