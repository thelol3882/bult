export type DeployStatus = 'building' | 'starting' | 'running' | 'failed';

export const isDeployFinished = (status: DeployStatus): boolean =>
    status === 'running' || status === 'failed';

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
