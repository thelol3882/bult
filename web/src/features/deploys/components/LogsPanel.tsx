'use client';

import { useEffect, useRef, useState } from 'react';
import { Alert, Card, Loader, SegmentedControl } from '@mantine/core';
import { IconAlertCircle, IconTerminal2 } from '@tabler/icons-react';
import { Mono } from '@/shared/components';
import { useLogs } from '../hooks/useLogs';
import classes from './LogsPanel.module.css';

const TAILS = ['100', '200', '500', '1000'];
const NEAR_BOTTOM_PX = 40;

/** Output of the running replica; mounted only while its tab is visible, so polling stops with it. */
export function LogsPanel({ name }: { name: string }) {
    const [tail, setTail] = useState('200');
    const { logs, error, isLoading } = useLogs(name, Number(tail));

    const viewport = useRef<HTMLPreElement>(null);
    const stickToBottom = useRef(true);

    useEffect(() => {
        const el = viewport.current;
        if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
    }, [logs]);

    const onScroll = () => {
        const el = viewport.current;
        if (el) {
            stickToBottom.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
        }
    };

    return (
        <Card padding={0}>
            <div className={classes.head}>
                <IconTerminal2 size={18} color="var(--sky-7)" />
                <h3>Logs</h3>
                {logs?.deploy_id && (
                    <Mono className={classes.muted}>{logs.deploy_id.slice(0, 8)}</Mono>
                )}
                <span className={classes.spacer} />
                <span className={classes.muted}>Last</span>
                <SegmentedControl size="xs" data={TAILS} value={tail} onChange={setTail} />
                <span className={classes.muted}>lines, updates every 3 s</span>
            </div>

            {isLoading && (
                <div className={classes.state}>
                    <Loader size="sm" />
                </div>
            )}

            {error && !logs && (
                <div className={classes.pad}>
                    <Alert
                        color="red"
                        icon={<IconAlertCircle size={16} />}
                        title="Could not load logs"
                    >
                        {error.message}
                    </Alert>
                </div>
            )}

            {logs && logs.deploy_id === null && (
                <p className={classes.empty}>
                    No running deploy. Logs are shown for the running deploy only.
                </p>
            )}

            {logs && logs.deploy_id !== null && logs.lines.length === 0 && (
                <p className={classes.empty}>No output yet.</p>
            )}

            {logs && logs.lines.length > 0 && (
                <pre ref={viewport} className={classes.viewport} onScroll={onScroll}>
                    {logs.lines.join('\n')}
                </pre>
            )}
        </Card>
    );
}
