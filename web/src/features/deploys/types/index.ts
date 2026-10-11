import type { DeployStatus } from '@/shared/types';

export interface Deploy {
    id: string;
    app_name: string;
    status: DeployStatus;
    commit_sha: string;
    image: string;
    node: string;
    host_port: number;
    error: string;
    created_at: string;
}

export interface DeployArgs {
    name: string;
    id: string;
}
