import type { DeployStatus } from '@/shared/types';

export type ReplicaStatus = 'running' | 'unhealthy';

/** One running container of a deploy; `unhealthy`: its node stopped reporting. */
export interface DeployReplica {
    index: number;
    node: string;
    host_port: number;
    status: ReplicaStatus;
}

export interface Deploy {
    id: string;
    app_name: string;
    status: DeployStatus;
    commit_sha: string;
    image: string;
    desired_replicas: number;
    /** Running replicas on ready nodes: shown as ready/desired. */
    ready_replicas: number;
    /** The running replicas, by index. */
    replicas: DeployReplica[];
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
    /** Index of the replica the lines come from. */
    replica: number | null;
    lines: string[];
}

export interface ReplicasResult {
    replicas: number;
    /** The running deploy, or the deploy that starts a stopped app; null when stopped. */
    deploy: Deploy | null;
}

export interface SetReplicasArgs {
    name: string;
    replicas: number;
}

export interface DeployArgs {
    name: string;
    id: string;
}
