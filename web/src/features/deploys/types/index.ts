import type { DeployStatus } from '@/shared/types';

/**
 * running: serving. unhealthy: failing its health check or its node stopped reporting.
 * exited / oom: the container died and is replaced after a backoff. crashloop: the platform
 * gave up replacing it. lost: its node died and a replacement is being scheduled.
 */
export type ReplicaStatus = 'running' | 'unhealthy' | 'exited' | 'oom' | 'crashloop' | 'lost';

/** One container of a deploy, with what is known about its last failure. */
export interface DeployReplica {
    index: number;
    node: string;
    host_port: number;
    status: ReplicaStatus;
    /** Exit code of the last death; null while it never died. */
    exit_code: number | null;
    /** Failures in the recent window (the platform gives up after 5 in 10 minutes). */
    recent_failures: number;
    /** User-facing cause such as "exited with code 1"; empty when healthy. */
    reason: string;
    /** Last lines of the app's own output captured at the last failure; may be empty. */
    log_tail: string[];
    /** When the platform tries again (ISO); null when no restart is scheduled. */
    retry_at: string | null;
}

export interface Deploy {
    id: string;
    app_name: string;
    status: DeployStatus;
    commit_sha: string;
    image: string;
    desired_replicas: number;
    /** Running and healthy replicas on ready nodes: shown as ready/desired. */
    ready_replicas: number;
    /** The replicas, by index. */
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
