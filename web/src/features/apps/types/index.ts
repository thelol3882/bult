export type Preset = 'fastapi' | 'express';

export interface BultApp {
    name: string;
    preset: Preset;
    repo_url: string;
    branch: string;
    subdir: string;
    created_at: string;
    url: string;
}

export interface AppCreate {
    name: string;
    preset: Preset;
    repo_url: string;
    branch: string;
    subdir: string;
}
