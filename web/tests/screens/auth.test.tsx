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
  return { signIn };
}

afterEach(() => { vi.restoreAllMocks(); });

describe('AuthScreen — GitLab OAuth', () => {
  it('sign-in shows the GitLab button and no credential inputs', () => {
    stubApp();
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    expect(screen.getByText(/Welcome back/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Continue with GitLab/i })).toBeTruthy();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(document.querySelector('input')).toBeNull();
  });

  it('clicking the GitLab button calls signIn', async () => {
    const { signIn } = stubApp();
    render(<MemoryRouter><AuthScreen mode="signin" /></MemoryRouter>);
    await userEvent.click(screen.getByRole('button', { name: /Continue with GitLab/i }));
    expect(signIn).toHaveBeenCalledWith('', '');
  });

  it('sign-up shows the create-account heading and the same GitLab button', () => {
    stubApp();
    render(<MemoryRouter><AuthScreen mode="signup" /></MemoryRouter>);
    expect(screen.getByText(/Create account/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Continue with GitLab/i })).toBeTruthy();
  });
});
