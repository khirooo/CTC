import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider, useApp } from '@/store/AppContext';
import { makeFakeApi } from '../helpers/fakeApi';

function Probe() {
  const { session, signIn } = useApp();
  return (
    <div>
      <span data-testid="sess">{session ? session.role : 'none'}</span>
      <button onClick={() => signIn('ada@example.com', 'x')}>in</button>
    </div>
  );
}

describe('AppContext', () => {
  it('signs in and exposes the session', async () => {
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'ctx.test' });
    render(<AppProvider api={api}><Probe /></AppProvider>);
    expect(screen.getByTestId('sess')).toHaveTextContent('none');
    await userEvent.click(screen.getByText('in'));
    await waitFor(() => expect(screen.getByTestId('sess')).toHaveTextContent('giver'));
  });

  it('shows a retry panel when the bootstrap getSession rejects, then recovers on retry', async () => {
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'ctx.boot' });
    // First call (mount) rejects; subsequent calls (retry) fall through to the
    // real fake, which returns null (logged out) — enough to clear the panel.
    const real = api.getSession.bind(api);
    let calls = 0;
    api.getSession = (async () => {
      calls += 1;
      if (calls === 1) throw new Error('network down');
      return real();
    }) as typeof api.getSession;

    render(<AppProvider api={api}><Probe /></AppProvider>);

    // Bootstrap rejected → retry panel, children (Probe) not rendered.
    await waitFor(() => expect(screen.getByText(/can't reach ctc/i)).toBeInTheDocument());
    expect(screen.queryByTestId('sess')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: /retry/i }));

    // Retry succeeded (null session) → panel gone, app renders.
    await waitFor(() => expect(screen.getByTestId('sess')).toHaveTextContent('none'));
    expect(screen.queryByText(/can't reach ctc/i)).toBeNull();
  });
});
