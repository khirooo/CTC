import { describe, it, expect, vi, afterEach } from 'vitest';
import { HttpCtcApi } from '@/api/HttpCtcApi';

const BASE = 'http://localhost:8090/api';

afterEach(() => {
  vi.unstubAllGlobals();
});

// Helper: stub global fetch with a JSON response
function mockFetch(status: number, body: unknown) {
  const res = new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res));
}

describe('getCliCredentials (HttpCtcApi)', () => {
  const api = new HttpCtcApi(BASE);

  it('throws when the server returns 401 (not authenticated)', async () => {
    // HttpCtcApi calls POST /proxy-token; the real server rejects unauthenticated requests.
    // In mockApi the guard was in-memory; here the transport layer throws CtcApiError on !res.ok.
    mockFetch(401, { error: 'unauthorized', message: 'not authenticated' });
    await expect(api.getCliCredentials()).rejects.toThrow();
  });

  it('returns a well-formed token, proxyHost, installCommand, and caFingerprint', async () => {
    const fakeToken = 'github_pat_' + 'A'.repeat(36);
    mockFetch(200, { token: fakeToken, ca_fingerprint: 'sha256:abc' });
    const creds = await api.getCliCredentials();
    expect(creds.token).toMatch(/^github_pat_/);
    expect(creds.token.length).toBeGreaterThanOrEqual(40);
    // proxyHost and installCommand are CLIENT-SYNTHESIZED by HttpCtcApi from
    // VITE_PROXY_HOST / VITE_CTC_HOST env vars and window.location.protocol —
    // they are NOT passed through from the server body, so the stub intentionally
    // omits them and we assert only their shape here.
    expect(creds.proxyHost).toContain(':');            // host:port shape
    expect(creds.installCommand).toContain('install.sh');
    // jsdom loads over http by default → no -k (see the scheme-specific tests below).
    expect(creds.installCommand).toContain('curl -fsSL ');
    expect(creds.installCommand).not.toContain('-fsSLk');
    expect(creds).toHaveProperty('caFingerprint');
  });

  it('installCommand embeds the token as a --token one-liner', async () => {
    const fakeToken = 'github_pat_' + 'B'.repeat(36);
    mockFetch(200, { token: fakeToken, ca_fingerprint: null });
    const creds = await api.getCliCredentials();
    expect(creds.installCommand).toContain(`| sh -s -- --token ${fakeToken}`);
    expect(creds.installCommand).toContain('curl -fsSL ');
  });

  it('omits -k under plain http (no TLS to skip; -k would only invite a MITM swap)', async () => {
    Object.defineProperty(window, 'location', { value: { protocol: 'http:' }, writable: true, configurable: true });
    mockFetch(200, { token: 'github_pat_' + 'D'.repeat(36), ca_fingerprint: null });
    const creds = await api.getCliCredentials();
    expect(creds.installCommand).toContain('curl -fsSL http://');
    expect(creds.installCommand).not.toContain('-fsSLk');
  });

  it('uses -k only under https (self-signed CA case)', async () => {
    Object.defineProperty(window, 'location', { value: { protocol: 'https:' }, writable: true, configurable: true });
    mockFetch(200, { token: 'github_pat_' + 'E'.repeat(36), ca_fingerprint: null });
    const creds = await api.getCliCredentials();
    expect(creds.installCommand).toContain('curl -fsSLk https://');
  });

  it('calls POST /proxy-token on each invocation (server owns idempotency, not the client)', async () => {
    // mockApi returned the same token for repeated calls (localStorage-backed idempotency).
    // HttpCtcApi always POSTs to /proxy-token; idempotency is a server concern.
    // We verify the client makes the request correctly on each call.
    const fakeToken = 'github_pat_' + 'C'.repeat(36);
    const makeRes = () => new Response(JSON.stringify({ token: fakeToken, ca_fingerprint: null }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(makeRes()));
    vi.stubGlobal('fetch', fetchMock);

    const a = await api.getCliCredentials();
    const b = await api.getCliCredentials();
    expect(a.token).toBe(fakeToken);
    expect(b.token).toBe(fakeToken);
    // Two separate network calls were made
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[0][0] as string)).toContain('/proxy-token');
    expect((fetchMock.mock.calls[1][0] as string)).toContain('/proxy-token');
  });
});
