/** "host/app@sha256:<hex>" -> "sha256:9f2c07b1d4e8…a51c0e41a"; anything else is returned as is. */
export function shortDigest(image: string): string {
    const digest = image.split('@')[1];
    if (!digest) return image;
    const [algo, hex] = digest.split(':');
    if (!hex || hex.length <= 20) return digest;
    return `${algo}:${hex.slice(0, 12)}…${hex.slice(-9)}`;
}

export const shortSha = (sha: string): string => sha.slice(0, 7);
