// Mirrors control-plane/app/apps/schemas/apps.py.
export const RESERVED_NAMES: ReadonlySet<string> = new Set(['api', 'www', 'admin', 'registry']);
export const DNS_LABEL_REGEX = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/** Returns an error message, or null when the name is a valid app name. */
export function validateAppName(name: string): string | null {
    if (name.length === 0) return 'Name is required';
    if (name.length > 63) return 'Name must be at most 63 characters';
    if (/[A-Z]/.test(name)) return 'Use lowercase letters only';
    if (!DNS_LABEL_REGEX.test(name)) {
        return 'Use lowercase letters, digits and hyphens; start and end with a letter or digit';
    }
    if (RESERVED_NAMES.has(name)) return `"${name}" is reserved by the platform`;
    return null;
}

export function validateRepoUrl(value: string): string | null {
    if (value.trim().length === 0) return 'Repository URL is required';
    try {
        const url = new URL(value.trim());
        if (url.protocol !== 'https:') return 'Repository URL must use https';
        return null;
    } catch {
        return 'Enter a valid URL, e.g. https://github.com/user/repo';
    }
}

export const HEALTH_PATH_HELP = "Empty = TCP check on the app's port. 2xx/3xx = healthy.";

// Mirrors the API: starts with "/", at most 200 characters from this set; empty = TCP check.
const HEALTH_PATH_REGEX = /^\/[A-Za-z0-9._~\-/?=&%]*$/;

export function validateHealthPath(value: string): string | null {
    const path = value.trim();
    if (path === '') return null;
    if (path.length > 200) return 'Path must be at most 200 characters';
    if (!path.startsWith('/')) return 'Path must start with "/"';
    if (!HEALTH_PATH_REGEX.test(path)) return 'Use only letters, digits and . _ ~ - / ? = & %';
    return null;
}
