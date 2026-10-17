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
    /** Set when the deploy reuses the image of this earlier deploy (start, rollback). */
    source_deploy_id: string;
    /** It ran at some point and has an image: a rollback or start can reuse it. */
    restorable: boolean;
}

export interface AppLogs {
    /** null when no deploy is running. */
    deploy_id: string | null;
    lines: string[];
}

export interface DeployArgs {
    name: string;
    id: string;
}
