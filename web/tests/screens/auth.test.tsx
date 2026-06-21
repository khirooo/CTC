import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthScreen } from '@/screens/Auth/AuthScreen';
import * as AppCtx from '@/store/AppContext';

function stubApp(signIn = vi.fn()) {
  vi.spyOn(AppCtx, 'useApp').mockReturnValue({
    session: null, signIn, completeOnboarding: vi.fn(),
    signOut: vi.fn(), api: {} as any, refresh: vi.fn(),
  } as any);
  return signIn;
}

afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

describe('AuthScreen (OAuth-only)', () => {
  it('sign-in shows the GHE button and no password field', () => {
    stubApp();
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    expect(screen.getByText(/Welcome back/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /github enterprise/i })).toBeTruthy();
    // OAuth-only: no credential input fields at all. (Decorative terminal text in
    // the right column may mention "password" — assert on inputs, not on copy.)
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(document.querySelector('input')).toBeNull();
  });

  it('clicking the GHE button starts the OAuth sign-in', async () => {
    const signIn = stubApp();
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    await userEvent.click(screen.getByRole('button', { name: /github enterprise/i }));
    expect(signIn).toHaveBeenCalled();
  });

  it('sign-up shows the create-account heading and the same GHE button', () => {
    stubApp();
    render(<MemoryRouter><AuthScreen mode="signup" /></MemoryRouter>);
    expect(screen.getByText(/Create account/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /github enterprise/i })).toBeTruthy();
  });
});
