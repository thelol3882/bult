import type { ReactNode } from 'react';
import { Alert, Badge, Button, Card, Loader } from '@mantine/core';
import {
    IconAlertCircle,
    IconCloudUpload,
    IconExternalLink,
    IconPlayerStop,
} from '@tabler/icons-react';
import { isDeployCancellable } from '@/shared/types';
import type { ApiError } from '@/shared/api';
import { IdText, Mono, StatusBadge } from '@/shared/components';
import { shortDigest, shortSha } from '@/shared/utils/digest';
import { formatReplicas } from '../services/replicas';
import type { Deploy } from '../types';
import classes from './DeployCard.module.css';

interface DeployCardProps {
    deploy?: Deploy;
    error?: ApiError;
    isLoading: boolean;
    /** The app's public URL as returned by the API; the open button shows only when running. */
    appUrl?: string;
    /** Asks to cancel the deploy; the button shows while it is queued or building. */
    onCancel?: (deploy: Deploy) => void;
}

export function DeployCard({ deploy, error, isLoading, appUrl, onCancel }: DeployCardProps) {
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
                        {deploy.source_deploy_id && (
                            <Row label="Source">
                                <span className={classes.muted}>
                                    image of deploy{' '}
                                    <Mono>{deploy.source_deploy_id.slice(0, 8)}</Mono>
                                </span>
                            </Row>
                        )}
                        <Row label="Replicas">
                            <Mono>
                                {formatReplicas(deploy.ready_replicas, deploy.desired_replicas)}
                            </Mono>
                            <span className={classes.muted}>&nbsp;ready</span>
                        </Row>
                    </dl>
                    {deploy.replicas.length > 0 && (
                        <ul className={classes.replicas} aria-label="Replicas">
                            {deploy.replicas.map((r) => (
                                <li key={r.index}>
                                    <Mono>#{r.index}</Mono>
                                    <Mono>
                                        {r.node}:{r.host_port}
                                    </Mono>
                                    <Badge
                                        size="sm"
                                        variant="light"
                                        color={r.status === 'running' ? 'green' : 'red'}
                                    >
                                        {r.status === 'running' ? 'Running' : 'Node not reporting'}
                                    </Badge>
                                </li>
                            ))}
                        </ul>
                    )}
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
                    {onCancel && isDeployCancellable(deploy.status) && (
                        <div className={classes.open}>
                            <Button
                                color="red"
                                variant="light"
                                leftSection={<IconPlayerStop size={16} />}
                                onClick={() => onCancel(deploy)}
                            >
                                Cancel deploy
                            </Button>
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
