import { isDeployActive, type DeployStatus } from '@/shared/types';
import type { DeployReplica, ReplicaStatus } from '../types';

export const MAX_REPLICAS = 5;

/** "2/3": replicas ready out of the replicas the deploy wants. */
export const formatReplicas = (ready: number, desired: number): string => `${ready}/${desired}`;

interface ScaleContext {
    /** Status of the newest deploy, if any. */
    newestStatus?: DeployStatus;
    /** Desired replicas of the app now. */
    current: number;
    /** An image exists to start a stopped app from (or more history may hold one). */
    hasImageToStart: boolean;
}

/** Why the replica count cannot be changed right now; undefined when it can. */
export function scaleBlockedReason({
    newestStatus,
    current,
    hasImageToStart,
}: ScaleContext): string | undefined {
    if (newestStatus !== undefined && isDeployActive(newestStatus)) {
        return 'A deploy is in progress. Wait for it to finish.';
    }
    if (current === 0 && !hasImageToStart) {
        return 'Deploy the app first: there is no image to start.';
    }
    return undefined;
}

/** The count a stepper click leads to, kept inside 0..MAX_REPLICAS. */
export const stepReplicas = (value: number, delta: 1 | -1): number =>
    Math.min(MAX_REPLICAS, Math.max(0, value + delta));

const SCALE_ERRORS: Record<string, string> = {
    deploy_in_progress: 'This app has a deploy in progress. Wait for it to finish.',
    nothing_to_start: 'Deploy the app first: there is no image to start.',
    no_node_available: 'No node could start the replica. Try again later.',
};

/** User-facing text for the errors a scale request gives; undefined for any other code. */
export const scaleErrorMessage = (code: string | undefined): string | undefined =>
    code === undefined ? undefined : SCALE_ERRORS[code];

interface ReplicaStatusMeta {
    label: string;
    /** Mantine color name for the badge. */
    color: string;
    /** Short hint when the status itself is all the user gets (no reason from the API). */
    hint: string;
}

export const REPLICA_STATUS: Record<ReplicaStatus, ReplicaStatusMeta> = {
    running: { label: 'Running', color: 'green', hint: 'Serving traffic.' },
    unhealthy: {
        label: 'Unhealthy',
        color: 'yellow',
        hint: 'Running but failing its health check, or its node stopped reporting.',
    },
    exited: { label: 'Exited', color: 'orange', hint: 'The container died; it will be replaced.' },
    oom: { label: 'Out of memory', color: 'grape', hint: 'Killed for running out of memory.' },
    crashloop: {
        label: 'Crash loop',
        color: 'red',
        hint: 'Replaced too often; the platform gave up until the next deploy, scale or start.',
    },
    lost: {
        label: 'Node lost',
        color: 'gray',
        hint: 'Its node died; a replacement is being scheduled.',
    },
};

/** Seconds from `now` until an ISO timestamp (the API may send naive UTC); negative when past. */
function secondsUntil(iso: string, now: number): number {
    const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
    return Math.round((Date.parse(hasZone ? iso : `${iso}Z`) - now) / 1000);
}

/** "restarting in 20 s"; null when no restart is scheduled or its time has passed. */
export function retryLabel(retryAt: string | null, now: number = Date.now()): string | null {
    if (retryAt === null) return null;
    const seconds = secondsUntil(retryAt, now);
    if (seconds <= 0) return null;
    if (seconds < 60) return `restarting in ${seconds} s`;
    return `restarting in ${Math.ceil(seconds / 60)} min`;
}

/** The one line shown next to the badge: the API's reason, else the generic hint for the status. */
export const replicaHint = (r: DeployReplica): string =>
    r.reason || (r.status === 'running' ? '' : REPLICA_STATUS[r.status].hint);

/** A crashloop always has a panel; exited and oom have one when there is output to show. */
export function hasFailureDetails(r: DeployReplica): boolean {
    if (r.status === 'crashloop') return true;
    return (r.status === 'exited' || r.status === 'oom') && r.log_tail.length > 0;
}

/** Ready is below desired: some replica is not serving. */
export const isDegraded = (ready: number, desired: number): boolean => ready < desired;
