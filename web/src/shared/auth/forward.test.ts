import { describe, expect, it } from 'vitest';
import {
    buildUpstreamHeaders,
    buildUpstreamUrl,
    isSameOrigin,
    safeNext,
    shouldDestroySession,
} from './forward';

describe('buildUpstreamUrl', () => {
    it('joins segments and keeps the query', () => {
        expect(buildUpstreamUrl('http://api:8000/', ['apps', 'my app', 'deploys'], '?page=2')).toBe(
            'http://api:8000/apps/my%20app/deploys?page=2',
        );
    });

    it('rejects traversal segments', () => {
        expect(buildUpstreamUrl('http://api:8000', ['apps', '..', 'auth'], '')).toBeNull();
        expect(buildUpstreamUrl('http://api:8000', ['apps', ''], '')).toBeNull();
    });
});

describe('buildUpstreamHeaders', () => {
    it('sets the bearer token and drops cookies and a spoofed authorization', () => {
        const incoming = new Headers({
            cookie: 'bult_session=secret',
            authorization: 'Bearer attacker',
            'content-type': 'application/json',
        });
        const headers = buildUpstreamHeaders(incoming, 'real-token');
        expect(headers.get('authorization')).toBe('Bearer real-token');
        expect(headers.get('cookie')).toBeNull();
        expect(headers.get('content-type')).toBe('application/json');
    });
});

describe('shouldDestroySession', () => {
    it('only on 401', () => {
        expect(shouldDestroySession(401)).toBe(true);
        expect(shouldDestroySession(403)).toBe(false);
        expect(shouldDestroySession(500)).toBe(false);
    });
});

describe('safeNext', () => {
    it('keeps same-origin paths', () => {
        expect(safeNext('/apps/blog?deploy=1')).toBe('/apps/blog?deploy=1');
    });

    it('falls back for external, protocol-relative or auth targets', () => {
        for (const bad of ['https://evil.com', '//evil.com', '/\\evil.com', '/login', '', null]) {
            expect(safeNext(bad)).toBe('/apps');
        }
    });
});

describe('isSameOrigin', () => {
    const make = (method: string, headers: Record<string, string>) =>
        new Request('http://web:3000/api/apps', {
            method,
            headers: { host: 'localhost:3000', ...headers },
        });

    it('accepts a matching Origin or Referer', () => {
        expect(isSameOrigin(make('POST', { origin: 'http://localhost:3000' }))).toBe(true);
        expect(isSameOrigin(make('POST', { referer: 'http://localhost:3000/apps' }))).toBe(true);
    });

    it('rejects another origin, including a sibling subdomain', () => {
        expect(isSameOrigin(make('POST', { origin: 'http://blog.localhost:3000' }))).toBe(false);
        expect(isSameOrigin(make('DELETE', { origin: 'null' }))).toBe(false);
    });

    it('rejects an unsafe request with no Origin or Referer', () => {
        expect(isSameOrigin(make('POST', {}))).toBe(false);
        expect(isSameOrigin(make('PATCH', { referer: 'not a url' }))).toBe(false);
    });

    it('lets safe methods through without an Origin', () => {
        expect(isSameOrigin(make('GET', {}))).toBe(true);
    });

    it('honours forwarded host and proto', () => {
        const req = make('POST', {
            origin: 'https://dash.example.com',
            'x-forwarded-host': 'dash.example.com',
            'x-forwarded-proto': 'https',
        });
        expect(isSameOrigin(req)).toBe(true);
    });
});
