import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AuthScreen } from '@/screens/Auth/AuthScreen';
import * as AppCtx from '@/store/AppContext';

function stubApp(signIn = vi.fn()) {
  vi.spyOn(AppCtx, 'useApp').mockReturnValue({
    session: null, signIn,
    signOut: vi.fn(), api: {} as any, refresh: vi.fn(),
  } as any);
  return { signIn };
}

afterEach(() => { vi.restoreAllMocks(); });

describe('AuthScreen — GitLab OAuth', () => {
  it('shows the GitLab button and no credential inputs', () => {
    stubApp();
    render(<MemoryRouter><AuthScreen /></MemoryRouter>);
    expect(screen.getByText(/Welcome to CTC/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Continue with GitLab/i })).toBeTruthy();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(document.querySelector('input')).toBeNull();
  });

  it('clicking the GitLab button calls signIn', async () => {
    const { signIn } = stubApp();
    render(<MemoryRouter><AuthScreen /></MemoryRouter>);
    await userEvent.click(screen.getByRole('button', { name: /Continue with GitLab/i }));
    expect(signIn).toHaveBeenCalled();
  });
});
