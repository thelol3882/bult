export interface ApiError {
    status: number | 'network';
    message: string;
    fieldErrors?: Record<string, string>;
}

interface ValidationItem {
    loc?: unknown[];
    msg?: string;
}

const UNREACHABLE = 'API is unreachable';
// Non-JSON statuses that mean the API is down. Next's rewrite proxy answers a plain-text 500
// when the upstream refuses the connection; 502/503/504 come from real gateways.
const GATEWAY_STATUSES: ReadonlySet<number> = new Set([500, 502, 503, 504]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

// Pydantic prefixes validator messages with "Value error, ".
const cleanMessage = (msg: string): string => msg.replace(/^Value error,\s*/, '');

function fromValidation(items: ValidationItem[]): ApiError {
    const fieldErrors: Record<string, string> = {};
    for (const item of items) {
        const field = item.loc?.filter((part) => part !== 'body').at(-1);
        if (typeof field === 'string' && item.msg && !(field in fieldErrors)) {
            fieldErrors[field] = cleanMessage(item.msg);
        }
    }
    return { status: 422, message: 'Validation failed', fieldErrors };
}

/** Normalizes an RTK Query error (FetchBaseQueryError | SerializedError) into one shape. */
export function normalizeError(error: unknown): ApiError {
    if (!isRecord(error)) return { status: 'network', message: UNREACHABLE };

    const { status, data } = error;

    if (status === 'FETCH_ERROR' || status === 'TIMEOUT_ERROR') {
        return { status: 'network', message: UNREACHABLE };
    }

    if (status === 'PARSING_ERROR') {
        const original = typeof error.originalStatus === 'number' ? error.originalStatus : 0;
        if (GATEWAY_STATUSES.has(original)) return { status: 'network', message: UNREACHABLE };
        if (original >= 500) return { status: original, message: `Request failed (${original})` };
        return { status: original || 500, message: 'Unexpected response from the API' };
    }

    if (typeof status !== 'number') {
        return { status: 500, message: 'Something went wrong' };
    }

    const detail = isRecord(data) ? data.detail : undefined;

    if (status === 422 && Array.isArray(detail)) return fromValidation(detail as ValidationItem[]);

    if (typeof detail === 'string') return { status, message: detail };
    return { status, message: `Request failed (${status})` };
}
