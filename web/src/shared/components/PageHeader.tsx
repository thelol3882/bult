import type { ReactNode } from 'react';
import classes from './PageHeader.module.css';

interface PageHeaderProps {
    title: string;
    subtitle?: ReactNode;
    actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
    return (
        <div className={classes.root}>
            <div>
                <h1>{title}</h1>
                {subtitle && <p>{subtitle}</p>}
            </div>
            {actions && <div className={classes.actions}>{actions}</div>}
        </div>
    );
}
