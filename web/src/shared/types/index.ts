export type DeployStatus =
    | 'queued'
    | 'building'
    | 'starting'
    | 'running'
    | 'failed'
    | 'cancelled'
    | 'superseded'
    | 'stopped';

/** A queued, building or starting deploy: work in progress, keep polling it. */
export const isDeployActive = (status: DeployStatus): boolean =>
    status === 'queued' || status === 'building' || status === 'starting';

/** The API cancels only a queued or building deploy; `starting` is almost done. */
export const isDeployCancellable = (status: DeployStatus): boolean =>
    status === 'queued' || status === 'building';

export const isDeployFinished = (status: DeployStatus): boolean => !isDeployActive(status);

/** Page-number pagination envelope (`next`/`previous` are page numbers). */
export interface Page<T> {
    count: number;
    next: number | null;
    previous: number | null;
    results: T[];
}

/** Cursor pagination envelope. */
export interface CursorPage<T> {
    results: T[];
    next_cursor: string | null;
}
