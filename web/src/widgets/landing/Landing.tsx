import type { CSSProperties } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { Logo } from '@/shared/components';
import classes from './Landing.module.css';

const STEPS = [
    { title: 'Push', text: 'Commit to GitHub.' },
    { title: 'Build', text: 'One image, built once.' },
    { title: 'Run', text: 'Replicas behind nginx.' },
];

export function Landing() {
    return (
        <>
            <header className={classes.hero}>
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
                <div className={classes.inner}>
                    <nav className={classes.nav} aria-label="Main">
                        <Link href="/" className={classes.brand}>
                            <Logo />
                            bult
                            <small>бұлт = cloud</small>
                        </Link>
                        <div className={classes.navRight}>
                            <a href="https://github.com/thelol3882/bult" rel="noopener noreferrer">
                                GitHub
                            </a>
                            <Link href="/apps">Open dashboard</Link>
                        </div>
                    </nav>

                    <div className={classes.copy}>
                        <h1 aria-label="From git push to a live URL.">
                            <span className={classes.line} aria-hidden="true">
                                <span style={{ '--i': 0 } as CSSProperties}>From git push</span>
                            </span>
                            <span className={classes.line} aria-hidden="true">
                                <span style={{ '--i': 1 } as CSSProperties}>to a live URL.</span>
                            </span>
                        </h1>
                        <div className={classes.cta}>
                            <Link href="/new" className={`${classes.btn} ${classes.btnSun}`}>
                                Deploy an app
                            </Link>
                            <a href="#how" className={`${classes.btn} ${classes.btnGlass}`}>
                                How it works
                            </a>
                        </div>
                    </div>

                    <svg
                        className={classes.route}
                        width="260"
                        height="250"
                        viewBox="0 0 260 250"
                        aria-hidden="true"
                    >
                        <path
                            d="M70 4 C 62 120, 110 190, 190 232"
                            fill="none"
                            stroke="#fff"
                            strokeWidth="2"
                            strokeDasharray="2 8"
                            strokeLinecap="round"
                        />
                    </svg>
                    <div className={classes.flight} aria-hidden="true">
                        <div className={classes.packetX}>
                            <div className={classes.packetY}>
                                <span className={classes.packet}>
                                    <i />
                                    a3f9c1e
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className={classes.livepill} role="status">
                        <span className={classes.liveDot} />
                        <span className={classes.liveUrl}>https://blog.bult.localhost</span>
                        <small>Live</small>
                    </div>

                    <div className={classes.term} aria-label="Terminal: deploying blog">
                        <div className={classes.termBar}>
                            <i />
                            <i />
                            <i />
                            <span>~/code/blog</span>
                        </div>
                        <div className={classes.termBody}>
                            <div>
                                <span className={classes.prompt}>$</span> git push origin main
                            </div>
                            <div className={classes.l2}>
                                bult: building <span className={classes.url}>blog</span>{' '}
                                <span className={classes.dim}>(a3f9c1e)</span>
                            </div>
                            <div className={classes.l3}>
                                <span className={classes.ok}>✓</span> live at{' '}
                                <span className={classes.url}>blog.bult.localhost</span>
                            </div>
                        </div>
                    </div>
                </div>
            </header>

            <section className={classes.how} id="how">
                <ol className={classes.steps}>
                    {STEPS.map((step, i) => (
                        <li key={step.title} className={classes.step}>
                            <div className={classes.stepN}>{i + 1}</div>
                            <h3>{step.title}</h3>
                            <p>{step.text}</p>
                        </li>
                    ))}
                </ol>
                <p className={classes.credit}>
                    <a
                        href="https://unsplash.com/photos/white-cloud-sky-lNxMcE8mvIM"
                        rel="noopener noreferrer"
                    >
                        Photo: Kumiko Shimizu / Unsplash
                    </a>
                </p>
            </section>
        </>
    );
}
