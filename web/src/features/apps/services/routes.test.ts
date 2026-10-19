import { describe, expect, it } from 'vitest';
import {
    MAX_ROUTES,
    normalizePath,
    rowsFromRoutes,
    rowsToRoutes,
    validateRoutePath,
    validateRouteRows,
    type RouteRow,
} from './routes';

const row = (path: string, app = 'shop-api'): RouteRow => ({ id: path, path, app });

describe('validateRoutePath', () => {
    it('accepts paths like the API does', () => {
        for (const path of ['/api', '/api/', '/api/v1', '/a_b-c', '/0']) {
            expect(validateRoutePath(path)).toBeNull();
        }
    });

    it('rejects the root, missing slash, case, and odd characters', () => {
        for (const path of [
            '',
            '/',
            'api',
            '/API',
            '/a b',
            '/api//v1',
            '/-x',
            '/_x',
            '/a?b',
            '//',
        ]) {
            expect(validateRoutePath(path)).not.toBeNull();
        }
    });
});

describe('route rows', () => {
    it('normalizes the trailing slash away', () => {
        expect(normalizePath(' /api/ ')).toBe('/api');
        expect(rowsToRoutes([row('/api/')])).toEqual([{ path: '/api', app: 'shop-api' }]);
    });

    it('round-trips the routes of an app', () => {
        const routes = [{ path: '/api', app: 'shop-api' }];
        expect(rowsToRoutes(rowsFromRoutes(routes))).toEqual(routes);
    });

    it('flags duplicates after normalizing, missing targets and the limit', () => {
        expect(validateRouteRows([row('/api'), row('/api/')])).toEqual({
            'rows.1.path': 'Paths must be unique',
        });
        expect(validateRouteRows([row('/api', '')])).toEqual({ 'rows.0.app': 'Choose an app' });

        const many = Array.from({ length: MAX_ROUTES + 1 }, (_, i) => row(`/p${i}`));
        expect(validateRouteRows(many).rows).toBeDefined();
    });

    it('is valid when empty', () => {
        expect(validateRouteRows([])).toEqual({});
    });
});
