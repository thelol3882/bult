import type { ComponentPropsWithoutRef } from 'react';
import classes from './Mono.module.css';

export function Mono({ className, ...props }: ComponentPropsWithoutRef<'span'>) {
    return <span {...props} className={[classes.mono, className].filter(Boolean).join(' ')} />;
}
