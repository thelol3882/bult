'use client';

import type { ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { Logo } from '@/shared/components';
import classes from './ErrorScreen.module.css';

export interface ErrorAction {
    label: string;
    href?: string;
    onClick?: () => void;
    /** Primary actions use the sun-gold fill; the rest use a glass fill. */
    primary?: boolean;
}

interface ErrorScreenProps {
    /** Three characters; the middle one is replaced by the cloud, e.g. "404". */
    code: string;
    title: string;
    description?: string;
    actions: ErrorAction[];
    children?: ReactNode;
}

/** Soft cumulus wisp: feathered white puffs, eroded edge, warm top-right light, bluish underside. */
function Cloud() {
    // Each puff: [cx, cy, r]. Together they form a loose, slightly hollow mass reading as "0".
    const puffs: [number, number, number][] = [
        [92, 140, 52],
        [138, 96, 58],
        [196, 84, 56],
        [246, 120, 52],
        [238, 168, 46],
        [178, 186, 50],
        [116, 182, 44],
        [60, 160, 34],
    ];
    return (
        <svg
            className={classes.cloud}
            viewBox="20 40 285 210"
            overflow="visible"
            aria-hidden="true"
        >
            <defs>
                <radialGradient id="cloudPuff">
                    <stop offset="0" stopColor="#fff" stopOpacity="1" />
                    <stop offset="0.45" stopColor="#fff" stopOpacity="0.72" />
                    <stop offset="1" stopColor="#fff" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="cloudShade" cx="0.5" cy="0.7" r="0.6">
                    <stop offset="0" stopColor="#8fc4e6" stopOpacity="0.5" />
                    <stop offset="1" stopColor="#8fc4e6" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="cloudWarm" cx="0.5" cy="0.5" r="0.5">
                    <stop offset="0" stopColor="#fff2cf" stopOpacity="0.85" />
                    <stop offset="1" stopColor="#fff2cf" stopOpacity="0" />
                </radialGradient>
                <filter id="cloudErode" x="-20%" y="-20%" width="140%" height="140%">
                    <feTurbulence
                        type="fractalNoise"
                        baseFrequency="0.018 0.026"
                        numOctaves="3"
                        seed="7"
                        result="noise"
                    />
                    <feDisplacementMap
                        in="SourceGraphic"
                        in2="noise"
                        scale="30"
                        xChannelSelector="R"
                        yChannelSelector="G"
                        result="eroded"
                    />
                    <feGaussianBlur in="eroded" stdDeviation="4" />
                </filter>
            </defs>
            <g opacity="0.92" filter="url(#cloudErode)">
                <ellipse cx="165" cy="215" rx="120" ry="38" fill="url(#cloudShade)" />
                {puffs.map(([cx, cy, r]) => (
                    <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} fill="url(#cloudPuff)" />
                ))}
                <circle cx="228" cy="92" r="46" fill="url(#cloudWarm)" />
                <circle cx="250" cy="128" r="30" fill="url(#cloudWarm)" />
            </g>
        </svg>
    );
}

/** Full-screen sky with a big status code whose middle "0" is a cloud. */
export function ErrorScreen({ code, title, description, actions, children }: ErrorScreenProps) {
    const [first, , last] = code;

    return (
        <main className={classes.root}>
            <div className={classes.sky} aria-hidden="true">
                <Image
                    src="/images/sky-hero.jpg"
                    alt=""
                    fill
                    priority
                    sizes="100vw"
                    className={classes.photo}
                />
            </div>
            <div className={classes.glow} aria-hidden="true" />

            <Link href="/" className={classes.brand}>
                <Logo />
                bult
            </Link>

            <div className={classes.content}>
                <div className={classes.code} role="img" aria-label={`Error ${code}`}>
                    <span aria-hidden="true">{first}</span>
                    <Cloud />
                    <span aria-hidden="true">{last}</span>
                </div>
                <h1 className={classes.title}>{title}</h1>
                {description && <p className={classes.description}>{description}</p>}
                <div className={classes.actions}>
                    {actions.map(({ label, href, onClick, primary }) => {
                        const className = `${classes.btn} ${primary ? classes.btnSun : classes.btnGlass}`;
                        return href ? (
                            <Link key={label} href={href} className={className}>
                                {label}
                            </Link>
                        ) : (
                            <button
                                key={label}
                                type="button"
                                onClick={onClick}
                                className={className}
                            >
                                {label}
                            </button>
                        );
                    })}
                </div>
                {children}
            </div>
        </main>
    );
}
