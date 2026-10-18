export type NodeStatus = 'ready' | 'unhealthy';
export type NodeRole = 'builder' | 'runner' | 'both';

export interface PlatformNode {
    name: string;
    role: NodeRole;
    status: NodeStatus;
    /** ISO timestamp of the last heartbeat. */
    last_seen_at: string;
    /** Running replicas placed on the node. */
    replicas: number;
    version: string;
    cpus: number;
    memory_bytes: number;
}
