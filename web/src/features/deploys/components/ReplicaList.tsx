'use client';

import { useId } from 'react';
import { Badge, Collapse, Tooltip, UnstyledButton } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconChevronDown } from '@tabler/icons-react';
import { Mono } from '@/shared/components';
import { hasFailureDetails, REPLICA_STATUS, replicaHint, retryLabel } from '../services/replicas';
import type { DeployReplica } from '../types';
import classes from './ReplicaList.module.css';

export function ReplicaList({ replicas }: { replicas: DeployReplica[] }) {
    return (
        <ul className={classes.list} aria-label="Replicas">
            {replicas.map((r) => (
                <ReplicaRow key={r.index} replica={r} />
            ))}
        </ul>
    );
}

function ReplicaRow({ replica: r }: { replica: DeployReplica }) {
    const meta = REPLICA_STATUS[r.status];
    const details = hasFailureDetails(r);
    // A crash loop is the one state that needs the user to act, so its output starts open.
    const [open, { toggle }] = useDisclosure(r.status === 'crashloop');
    const panelId = useId();
    const hint = replicaHint(r);
    const retry = retryLabel(r.retry_at);

    return (
        <li>
            <div className={classes.row}>
                <Mono>#{r.index}</Mono>
                <Mono>
                    {r.node}:{r.host_port}
                </Mono>
                <Tooltip label={meta.hint} multiline maw={260}>
                    <Badge size="sm" variant="light" color={meta.color}>
                        {meta.label}
                    </Badge>
                </Tooltip>
            </div>
            {(hint || retry) && (
                <p className={classes.hint}>
                    {hint}
                    {hint && retry && ' · '}
                    {retry}
                </p>
            )}
            {details && (
                <>
                    <UnstyledButton
                        className={classes.toggle}
                        onClick={toggle}
                        aria-expanded={open}
                        aria-controls={panelId}
                    >
                        <IconChevronDown size={14} data-open={open} className={classes.chevron} />
                        {open ? 'Hide details' : 'Show details'}
                    </UnstyledButton>
                    <Collapse in={open} id={panelId}>
                        <dl className={classes.facts}>
                            <div>
                                <dt>Exit code</dt>
                                <dd>{r.exit_code === null ? '-' : r.exit_code}</dd>
                            </div>
                            <div>
                                <dt>Reason</dt>
                                <dd>{r.reason || '-'}</dd>
                            </div>
                            <div>
                                <dt>Failures</dt>
                                <dd>failed {r.recent_failures} times recently</dd>
                            </div>
                        </dl>
                        {r.log_tail.length > 0 ? (
                            <pre className={classes.log}>{r.log_tail.join('\n')}</pre>
                        ) : (
                            <p className={classes.hint}>No output captured.</p>
                        )}
                    </Collapse>
                </>
            )}
        </li>
    );
}
