import { describe, it, expect, beforeEach } from 'vitest';
import { mockApi } from '../mockApi';

describe('getCliCredentials', () => {
  beforeEach(() => localStorage.clear());

  it('throws when not authenticated', async () => {
    await expect(mockApi.getCliCredentials()).rejects.toThrow();
  });

  it('returns a stable, well-formed token + proxy host + install command for the signed-in user', async () => {
    await mockApi.signIn('demo@ctc.dev', 'x');
    const a = await mockApi.getCliCredentials();
    const b = await mockApi.getCliCredentials();
    expect(a.token).toMatch(/^github_pat_/);
    expect(a.token.length).toBeGreaterThanOrEqual(40);
    expect(a.token).toEqual(b.token);              // deterministic per user
    expect(a.proxyHost).toContain(':');            // host:port
    expect(a.installCommand).toContain('install.sh');
    expect(a.installCommand).toContain('-fsSLk');        // bootstrap tolerates self-signed cert
    expect(a).toHaveProperty('caFingerprint');
  });

  it('mock installCommand embeds the token as a --token one-liner', async () => {
    const { createMockApi } = await import('@/api/mockApi');
    const mockApi = createMockApi({ latencyMs: 0, storageKey: 'cli.embed' });
    await mockApi.signIn('ada@example.com', 'x');
    const c = await mockApi.getCliCredentials();
    expect(c.installCommand).toContain(`| sh -s -- --token ${c.token}`);
    expect(c.installCommand).toContain('curl -fsSLk');
  });
});
