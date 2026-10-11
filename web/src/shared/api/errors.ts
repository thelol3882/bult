export interface ApiError {
    status: number | 'network';
    message: string;
    /** Machine-readable error code from the API (e.g. "app_name_taken"). */
    code?: string;
    /** Request id: quote it when reporting a problem. */
    traceId?: string;
    fieldErrors?: Record<string, string>;
}

const UNREACHABLE = 'API is unreachable';
// Statuses that mean the API is down (the Next rewrite proxy answers a plain-text 500 on refused connections).
const GATEWAY_STATUSES: ReadonlySet<number> = new Set([500, 502, 503, 504]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

const stringOrUndefined = (value: unknown): string | undefined =>
    typeof value === 'string' ? value : undefined;

/** `fields` is {name: message}; keeps only string messages. */
function readFields(value: unknown): Record<string, string> {
    const result: Record<string, string> = {};
    if (!isRecord(value)) return result;
    for (const [name, message] of Object.entries(value)) {
        if (typeof message === 'string') result[name] = message;
    }
    return result;
}

/** The API error body: { detail, code, trace_id, field?, fields? }. */
function fromBody(status: number, data: Record<string, unknown>): ApiError | undefined {
    const detail = stringOrUndefined(data.detail);
    if (detail === undefined) return undefined;

    const fieldErrors = readFields(data.fields);
    const field = stringOrUndefined(data.field);
    if (field !== undefined) fieldErrors[field] = detail;

    const error: ApiError = { status, message: detail };
    const code = stringOrUndefined(data.code);
    if (code !== undefined) error.code = code;
    const traceId = stringOrUndefined(data.trace_id);
    if (traceId !== undefined) error.traceId = traceId;
    if (Object.keys(fieldErrors).length > 0) error.fieldErrors = fieldErrors;
    return error;
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

    const parsed = isRecord(data) ? fromBody(status, data) : undefined;
    return parsed ?? { status, message: `Request failed (${status})` };
}
