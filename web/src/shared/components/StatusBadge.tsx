import { Badge } from '@mantine/core';
import { deployStatusColor } from '@/theme/status';
import { isDeployActive, type DeployStatus } from '../types';
import classes from './StatusBadge.module.css';

const LABEL: Record<DeployStatus, string> = {
    queued: 'Queued',
    building: 'Building',
    starting: 'Starting',
    running: 'Running',
    failed: 'Failed',
};

export function StatusBadge({ status }: { status: DeployStatus }) {
    const color = deployStatusColor[status];
    return (
        <Badge
            color={color}
            leftSection={
                <span
                    className={`${classes.dot} ${isDeployActive(status) ? classes.pulse : ''}`}
                    style={{ background: `var(--mantine-color-${color}-5)` }}
                />
            }
        >
            {LABEL[status]}
        </Badge>
    );
}
