import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

dayjs.extend(relativeTime);

// The API may send naive UTC timestamps (no offset); treat those as UTC.
export function fromNow(iso: string): string {
    const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
    return dayjs(hasZone ? iso : `${iso}Z`).fromNow();
}
