import { isDeployActive, type DeployStatus } from '@/shared/types';

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
