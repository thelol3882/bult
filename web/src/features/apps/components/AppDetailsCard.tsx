import type { ReactNode } from 'react';
import { Card } from '@mantine/core';
import { IconExternalLink } from '@tabler/icons-react';
import { IdText, Mono } from '@/shared/components';
import { fromNow } from '@/shared/utils/date';
import type { BultApp } from '../types';
import classes from './AppDetailsCard.module.css';

export function AppDetailsCard({ app }: { app: BultApp }) {
    return (
        <Card padding={0}>
            <div className={classes.head}>
                <h3>Details</h3>
            </div>
            <dl className={classes.kv}>
                <Row label="Repository">
                    <IdText value={app.repo_url} />
                </Row>
                <Row label="Branch">
                    <Mono>{app.branch}</Mono>
                </Row>
                <Row label="Subdirectory">
                    {app.subdir ? (
                        <Mono>{app.subdir}</Mono>
                    ) : (
                        <span className={classes.muted}>/</span>
                    )}
                </Row>
                <Row label="Health check">
                    {app.health_path ? (
                        <Mono>{app.health_path}</Mono>
                    ) : (
                        <span className={classes.muted}>TCP</span>
                    )}
                </Row>
                <Row label="Preset">
                    <Mono>{app.preset}</Mono>
                </Row>
                <Row label="URL">
                    <a
                        href={app.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={classes.link}
                    >
                        <Mono>{app.url}</Mono>
                        <IconExternalLink size={13} />
                    </a>
                </Row>
                <Row label="State">
                    {app.replicas === 0 ? (
                        <span className={classes.muted}>Stopped</span>
                    ) : (
                        <Mono>
                            {app.replicas} {app.replicas === 1 ? 'replica' : 'replicas'}
                        </Mono>
                    )}
                </Row>
                <Row label="Created">{fromNow(app.created_at)}</Row>
            </dl>
        </Card>
    );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div>
            <dt>{label}</dt>
            <dd>{children}</dd>
        </div>
    );
}
