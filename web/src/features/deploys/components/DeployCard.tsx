import type { ReactNode } from 'react';
import { Alert, Button, Card, Loader } from '@mantine/core';
import { IconAlertCircle, IconCloudUpload, IconExternalLink } from '@tabler/icons-react';
import type { ApiError } from '@/shared/api';
import { IdText, Mono, StatusBadge } from '@/shared/components';
import { shortDigest, shortSha } from '@/shared/utils/digest';
import type { Deploy } from '../types';
import classes from './DeployCard.module.css';

interface DeployCardProps {
    deploy?: Deploy;
    error?: ApiError;
    isLoading: boolean;
    /** The app's public URL as returned by the API; the open button shows only when running. */
    appUrl?: string;
}

export function DeployCard({ deploy, error, isLoading, appUrl }: DeployCardProps) {
    return (
        <Card padding={0}>
            <div className={classes.head}>
                <IconCloudUpload size={18} color="var(--sky-7)" />
                <h3>Deploy</h3>
                {deploy && <StatusBadge status={deploy.status} />}
            </div>

            {isLoading && !deploy && (
                <div className={classes.state}>
                    <Loader size="sm" />
                </div>
            )}

            {error && !deploy && (
                <div className={classes.pad}>
                    <Alert color="red" icon={<IconAlertCircle size={16} />}>
                        {error.message}
                    </Alert>
                </div>
            )}

            {deploy && (
                <>
                    <dl className={classes.kv}>
                        <Row label="Commit">
                            {deploy.commit_sha ? (
                                <IdText
                                    value={deploy.commit_sha}
                                    display={shortSha(deploy.commit_sha)}
                                    chip
                                />
                            ) : (
                                <Pending />
                            )}
                        </Row>
                        <Row label="Image">
                            {deploy.image ? (
                                <IdText value={deploy.image} display={shortDigest(deploy.image)} />
                            ) : (
                                <Pending />
                            )}
                        </Row>
                        <Row label="Node">{deploy.node || <Pending />}</Row>
                        <Row label="Host port">
                            {deploy.host_port ? <Mono>{deploy.host_port}</Mono> : <Pending />}
                        </Row>
                    </dl>
                    {deploy.status === 'running' && appUrl && (
                        <div className={classes.open}>
                            <Button
                                component="a"
                                href={appUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                leftSection={<IconExternalLink size={16} />}
                            >
                                Open app
                            </Button>
                            <Mono>{appUrl}</Mono>
                        </div>
                    )}
                    {deploy.status === 'failed' && deploy.error && (
                        <div className={classes.pad}>
                            <Alert
                                color="red"
                                icon={<IconAlertCircle size={16} />}
                                title="Deploy failed"
                            >
                                <span className={classes.errorText}>{deploy.error}</span>
                            </Alert>
                        </div>
                    )}
                </>
            )}
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

const Pending = () => <span className={classes.muted}>pending</span>;
