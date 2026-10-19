import type { AppRoute } from '../types';

// Mirrors control-plane/app/apps/schemas/apps.py (RouteIn, RoutesUpdate).
export const ROUTE_PATH_REGEX = /^\/[a-z0-9][a-z0-9_-]*(\/[a-z0-9][a-z0-9_-]*)*$/;
export const MAX_ROUTES = 5;

/** One line of the editor; `app` is empty until a target is picked. */
export interface RouteRow {
    id: string;
    path: string;
    app: string;
}

export const rowsFromRoutes = (routes: AppRoute[]): RouteRow[] =>
    routes.map((r, i) => ({ id: `existing:${i}`, path: r.path, app: r.app }));

/** The path as the API stores it: no trailing slash. */
export const normalizePath = (path: string): string => path.trim().replace(/\/$/, '');

export function validateRoutePath(path: string): string | null {
    const normalized = normalizePath(path);
    if (normalized.length === 0) return 'Path is required';
    if (normalized.length > 100) return 'At most 100 characters';
    if (!ROUTE_PATH_REGEX.test(normalized)) {
        return 'Start with "/", then lowercase letters, digits, "-" or "_" (e.g. /api or /api/v1)';
    }
    return null;
}

export function rowsToRoutes(rows: RouteRow[]): AppRoute[] {
    return rows.map((r) => ({ path: normalizePath(r.path), app: r.app }));
}

/** Errors by `rows.<i>.<field>`, or `rows` for list-level ones; empty when valid. */
export function validateRouteRows(rows: RouteRow[]): Record<string, string> {
    const errors: Record<string, string> = {};
    if (rows.length > MAX_ROUTES) errors.rows = `At most ${MAX_ROUTES} routes`;

    const seen = new Set<string>();
    rows.forEach((row, i) => {
        const pathError = validateRoutePath(row.path);
        if (pathError) {
            errors[`rows.${i}.path`] = pathError;
        } else if (seen.has(normalizePath(row.path))) {
            errors[`rows.${i}.path`] = 'Paths must be unique';
        }
        seen.add(normalizePath(row.path));
        if (!row.app) errors[`rows.${i}.app`] = 'Choose an app';
    });
    return errors;
}
