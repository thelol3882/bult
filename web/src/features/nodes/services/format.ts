import type { NodeRole } from '../types';

const GIB = 1024 ** 3;

/** "2.0 GiB"; "-" when the node did not report its memory. */
export function formatMemory(bytes: number): string {
    if (bytes <= 0) return '-';
    return `${(bytes / GIB).toFixed(1)} GiB`;
}

const ROLE_LABEL: Record<NodeRole, string> = {
    builder: 'Builder',
    runner: 'Runner',
    both: 'Builder + runner',
};

export const roleLabel = (role: NodeRole): string => ROLE_LABEL[role];

/** Seconds since an ISO timestamp, never negative (clocks of the API and the browser differ a bit). */
export function secondsSince(iso: string, now: number = Date.now()): number {
    const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
    const then = Date.parse(hasZone ? iso : `${iso}Z`);
    return Math.max(0, Math.round((now - then) / 1000));
}

/** "3 s ago", "2 min ago": heartbeats are seconds apart, so dayjs's "a few seconds ago" says too little. */
export function lastSeenLabel(iso: string, now: number = Date.now()): string {
    const seconds = secondsSince(iso, now);
    if (seconds < 60) return `${seconds} s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    return hours < 48 ? `${hours} h ago` : `${Math.floor(hours / 24)} d ago`;
}
