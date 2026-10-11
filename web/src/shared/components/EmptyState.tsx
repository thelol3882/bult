import type { ReactNode } from 'react';
import { IconAlertCircle } from '@tabler/icons-react';
import classes from './EmptyState.module.css';

interface EmptyStateProps {
    title: string;
    description?: string;
    action?: ReactNode;
    tone?: 'neutral' | 'error';
}

export function EmptyState({ title, description, action, tone = 'neutral' }: EmptyStateProps) {
    return (
        <div className={classes.root}>
            {tone === 'error' ? (
                <IconAlertCircle size={36} color="var(--red-7)" stroke={1.5} />
            ) : (
                <svg className={classes.art} viewBox="0 0 180 100" aria-hidden="true">
                    <circle cx="90" cy="50" r="48" fill="#e8f9fc" />
                    <circle cx="112" cy="36" r="22" fill="#fec50c" opacity=".2" />
                    <circle cx="112" cy="36" r="15" fill="#fec50c" />
                    <path
                        transform="translate(34 40) scale(.4667)"
                        fill="#fff"
                        d="M38 108a34 34 0 0 1-4-67.8A44 44 0 0 1 116 22a38 38 0 0 1 62 14 36 36 0 0 1 24 72z"
                    />
                </svg>
            )}
            <h3>{title}</h3>
            {description && <p>{description}</p>}
            {action && <div className={classes.action}>{action}</div>}
        </div>
    );
}
