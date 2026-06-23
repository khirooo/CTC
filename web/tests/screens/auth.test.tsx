import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthScreen } from '@/screens/Auth/AuthScreen';
import * as AppCtx from '@/store/AppContext';
import type { CtcApi } from '@/api/CtcApi';

type AuthMode = 'ghe_oauth' | 'email';

function stubApp(signIn = vi.fn(), authMode: AuthMode = 'ghe_oauth') {
  const api: Partial<CtcApi> = {
    getConfig: vi.fn().mockResolvedValue({ authMode }),
    startEmailLogin: vi.fn().mockResolvedValue(undefined),
  };
  vi.spyOn(AppCtx, 'useApp').mockReturnValue({
    session: null, signIn, completeOnboarding: vi.fn(),
    signOut: vi.fn(), api: api as CtcApi, refresh: vi.fn(),
  } as any);
  return { signIn, api };
}

afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

describe('AuthScreen — ghe_oauth mode', () => {
  it('sign-in shows the GHE button and no password field', async () => {
    stubApp(vi.fn(), 'ghe_oauth');
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    expect(screen.getByText(/Welcome back/i)).toBeInTheDocument();
    // Wait for config to load and button to appear
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /github enterprise/i })).toBeTruthy();
    });
    // OAuth-only: no credential input fields at all. (Decorative terminal text in
    // the right column may mention "password" — assert on inputs, not on copy.)
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(document.querySelector('input')).toBeNull();
  });

  it('clicking the GHE button starts the OAuth sign-in', async () => {
    const { signIn } = stubApp(vi.fn(), 'ghe_oauth');
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /github enterprise/i })).toBeTruthy();
    });
    await userEvent.click(screen.getByRole('button', { name: /github enterprise/i }));
    expect(signIn).toHaveBeenCalled();
  });

  it('sign-up shows the create-account heading and the same GHE button', async () => {
    stubApp(vi.fn(), 'ghe_oauth');
    render(<MemoryRouter><AuthScreen mode="signup" /></MemoryRouter>);
    expect(screen.getByText(/Create account/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /github enterprise/i })).toBeTruthy();
    });
  });
});

describe('AuthScreen — email mode', () => {
  it('shows an email input and submit button instead of the GHE button', async () => {
    stubApp(vi.fn(), 'email');
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    await waitFor(() => {
      expect(document.querySelector('input[type="email"]')).toBeTruthy();
    });
    expect(screen.getByRole('button', { name: /send sign-in link/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /github enterprise/i })).toBeNull();
  });

  it('submitting the email form calls startEmailLogin and shows the confirmation', async () => {
    const { api } = stubApp(vi.fn(), 'email');
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    await waitFor(() => {
      expect(document.querySelector('input[type="email"]')).toBeTruthy();
    });
    const input = document.querySelector('input[type="email"]') as HTMLInputElement;
    await userEvent.type(input, 'test@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send sign-in link/i }));
    expect(api.startEmailLogin).toHaveBeenCalledWith('test@example.com');
    await waitFor(() => {
      expect(screen.getByText(/check your email/i)).toBeTruthy();
    });
  });

  it('shows an inline error and NOT the confirmation when startEmailLogin rejects', async () => {
    const api: Partial<CtcApi> = {
      getConfig: vi.fn().mockResolvedValue({ authMode: 'email' }),
      startEmailLogin: vi.fn().mockRejectedValue(new Error('Email not allowed')),
    };
    vi.spyOn(AppCtx, 'useApp').mockReturnValue({
      session: null, signIn: vi.fn(), completeOnboarding: vi.fn(),
      signOut: vi.fn(), api: api as CtcApi, refresh: vi.fn(),
    } as any);
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    await waitFor(() => {
      expect(document.querySelector('input[type="email"]')).toBeTruthy();
    });
    const input = document.querySelector('input[type="email"]') as HTMLInputElement;
    await userEvent.type(input, 'bad@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send sign-in link/i }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
      expect(screen.getByText(/Email not allowed/i)).toBeTruthy();
    });
    expect(screen.queryByText(/check your email/i)).toBeNull();
  });
});
