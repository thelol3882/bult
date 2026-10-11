import { Badge } from '@mantine/core';
import { deployStatusColor } from '@/theme/status';
import type { DeployStatus } from '../types';
import classes from './StatusBadge.module.css';

const LABEL: Record<DeployStatus, string> = {
    building: 'Building',
    starting: 'Starting',
    running: 'Running',
    failed: 'Failed',
};

const IN_PROGRESS: ReadonlySet<DeployStatus> = new Set(['building', 'starting']);

export function StatusBadge({ status }: { status: DeployStatus }) {
    const color = deployStatusColor[status];
    return (
        <Badge
            color={color}
            leftSection={
                <span
                    className={`${classes.dot} ${IN_PROGRESS.has(status) ? classes.pulse : ''}`}
                    style={{ background: `var(--mantine-color-${color}-5)` }}
                />
            }
        >
            {LABEL[status]}
        </Badge>
    );
}
