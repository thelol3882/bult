import { describe, expect, it } from 'vitest';
import { validateAppName, validateHealthPath, validateRepoUrl } from './validators';

describe('validateAppName', () => {
    it.each(['blog', 'a', 'my-app-2', '9lives', 'a'.repeat(63)])('accepts %s', (name) => {
        expect(validateAppName(name)).toBeNull();
    });

    it.each(['api', 'www', 'admin', 'registry'])('rejects reserved name %s', (name) => {
        expect(validateAppName(name)).toMatch(/reserved/);
    });

    it('rejects empty, too long, uppercase and malformed names', () => {
        expect(validateAppName('')).toMatch(/required/);
        expect(validateAppName('a'.repeat(64))).toMatch(/63/);
        expect(validateAppName('Blog')).toMatch(/lowercase/);
        expect(validateAppName('-blog')).not.toBeNull();
        expect(validateAppName('blog-')).not.toBeNull();
        expect(validateAppName('my_app')).not.toBeNull();
        expect(validateAppName('my app')).not.toBeNull();
    });
});

describe('validateRepoUrl', () => {
    it('accepts https URLs only', () => {
        expect(validateRepoUrl('https://github.com/thelol3882/bult')).toBeNull();
        expect(validateRepoUrl('http://github.com/a/b')).toMatch(/https/);
        expect(validateRepoUrl('git@github.com:a/b.git')).not.toBeNull();
        expect(validateRepoUrl('')).toMatch(/required/);
    });
});

describe('validateHealthPath', () => {
    it.each(['', '/', '/healthz', '/api/v1/health?full=1&x=a%20b', '/a.b_c~d-e'])(
        'accepts %j',
        (path) => {
            expect(validateHealthPath(path)).toBeNull();
        },
    );

    it('rejects a path that does not start with a slash', () => {
        expect(validateHealthPath('healthz')).toMatch(/start with/);
    });

    it('rejects characters outside the allowed set and long paths', () => {
        expect(validateHealthPath('/a b')).toMatch(/Use only/);
        expect(validateHealthPath('/<script>')).toMatch(/Use only/);
        expect(validateHealthPath('/' + 'a'.repeat(200))).toMatch(/200/);
        expect(validateHealthPath('/' + 'a'.repeat(199))).toBeNull();
    });
});
