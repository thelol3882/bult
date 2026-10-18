export type Preset = 'fastapi' | 'express';

export interface BultApp {
    name: string;
    preset: Preset;
    repo_url: string;
    branch: string;
    subdir: string;
    created_at: string;
    url: string;
    /** Desired replicas: 0 = stopped, 1 to 5 = running. */
    replicas: number;
    /** Names only: the values are write-only. */
    env_keys: string[];
}

export interface AppCreate {
    name: string;
    preset: Preset;
    repo_url: string;
    branch: string;
    subdir: string;
}

/** Variable name -> value. The API never returns values. */
export type EnvMap = Record<string, string>;

/** Partial update: only changed fields are sent; the name is immutable. */
export type AppUpdate = Partial<Omit<AppCreate, 'name'>>;
