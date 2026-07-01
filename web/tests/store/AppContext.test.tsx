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
});
