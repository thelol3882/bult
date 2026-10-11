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
