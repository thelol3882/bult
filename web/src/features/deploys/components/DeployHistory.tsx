import { Alert, Button, Card, Loader } from '@mantine/core';
import { IconAlertCircle, IconArrowBackUp, IconHistory } from '@tabler/icons-react';
import type { ApiError } from '@/shared/api';
import { Mono, StatusBadge } from '@/shared/components';
import { shortSha } from '@/shared/utils/digest';
import { fromNow } from '@/shared/utils/date';
import type { Deploy } from '../types';
import classes from './DeployHistory.module.css';

interface DeployHistoryProps {
    deploys: Deploy[];
    selectedId?: string;
    onSelect: (id: string) => void;
    isLoading: boolean;
    error?: ApiError;
    hasMore: boolean;
    isLoadingMore: boolean;
    onLoadMore: () => void;
    onRetry: () => void;
    /** Asks to run this deploy's image again; shown on deploys that can be restored. */
    onRollback?: (deploy: Deploy) => void;
    rollbackDisabled?: boolean;
}

export function DeployHistory({
    deploys,
    selectedId,
    onSelect,
    isLoading,
    error,
    hasMore,
    isLoadingMore,
    onLoadMore,
    onRetry,
    onRollback,
    rollbackDisabled,
}: DeployHistoryProps) {
    return (
        <Card padding={0}>
            <div className={classes.head}>
                <IconHistory size={18} color="var(--sky-7)" />
                <h3>Deploys</h3>
            </div>

            {isLoading && (
                <div className={classes.state}>
                    <Loader size="sm" />
                </div>
            )}

            {error && deploys.length === 0 && (
                <div className={classes.pad}>
                    <Alert
                        color="red"
                        icon={<IconAlertCircle size={16} />}
                        title="Could not load deploys"
                    >
                        {error.message}{' '}
                        <Button variant="subtle" size="compact-sm" onClick={onRetry}>
                            Try again
                        </Button>
                    </Alert>
                </div>
            )}

            {!isLoading && !error && deploys.length === 0 && (
                <p className={classes.empty}>No deploys yet.</p>
            )}

            {deploys.length > 0 && (
                <ul className={classes.list}>
                    {deploys.map((d) => (
                        <li key={d.id} className={classes.row}>
                            <button
                                type="button"
                                className={classes.item}
                                data-selected={d.id === selectedId || undefined}
                                onClick={() => onSelect(d.id)}
                            >
                                <StatusBadge status={d.status} />
                                <Mono>{d.commit_sha ? shortSha(d.commit_sha) : '-'}</Mono>
                                <span className={classes.muted}>{fromNow(d.created_at)}</span>
                                <span className={classes.where}>
                                    {d.node && d.host_port ? (
                                        <Mono>
                                            {d.node}:{d.host_port}
                                        </Mono>
                                    ) : null}
                                </span>
                                {d.status === 'failed' && d.error && (
                                    <span className={classes.error} title={d.error}>
                                        {d.error}
                                    </span>
                                )}
                            </button>
                            {onRollback && d.restorable && d.status !== 'running' && (
                                <Button
                                    variant="subtle"
                                    size="compact-sm"
                                    className={classes.action}
                                    leftSection={<IconArrowBackUp size={14} />}
                                    disabled={rollbackDisabled}
                                    onClick={() => onRollback(d)}
                                >
                                    Roll back
                                </Button>
                            )}
                        </li>
                    ))}
                </ul>
            )}

            {hasMore && (
                <div className={classes.more}>
                    <Button variant="default" loading={isLoadingMore} onClick={onLoadMore}>
                        Load more
                    </Button>
                </div>
            )}
        </Card>
    );
}
