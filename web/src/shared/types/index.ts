export type DeployStatus = 'building' | 'starting' | 'running' | 'failed';

export const isDeployFinished = (status: DeployStatus): boolean =>
    status === 'running' || status === 'failed';
