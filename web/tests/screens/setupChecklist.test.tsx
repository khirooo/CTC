import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@/store/AppContext';
import { SetupChecklist } from '@/screens/Dashboard/SetupChecklist';
import { makeFakeApi } from '../helpers/fakeApi';

function renderChecklist(session: Partial<import('@/domain/types').Session>) {
  const api = makeFakeApi();
  const s = { userId: 'u1', name: 'Test', role: 'consumer', onboarded: true, hasPat: false, ...session } as import('@/domain/types').Session;
  api._setSession(s);
  return render(
    <MemoryRouter>
      <AppProvider api={api} initialSession={s}>
        <SetupChecklist />
      </AppProvider>
    </MemoryRouter>,
  );
}

describe('SetupChecklist', () => {
  beforeEach(() => localStorage.clear());

  it('shows the terminal item for a fresh guest', async () => {
    renderChecklist({ role: 'consumer' });
    expect(await screen.findByText('Finish setting up')).toBeInTheDocument();
    expect(screen.getByText('Run the terminal setup')).toBeInTheDocument();
    expect(screen.queryByText('Connect your Copilot license')).toBeNull();
  });

  it('shows the license item for a host without a PAT, checked once hasPat', async () => {
    renderChecklist({ role: 'giver', hasPat: false });
    expect(await screen.findByText('Connect your Copilot license')).toBeInTheDocument();
  });

  it('expanding the terminal item fetches and shows the install command', async () => {
    renderChecklist({ role: 'consumer' });
    fireEvent.click(await screen.findByRole('button', { name: /show the command/i }));
    await waitFor(() => expect(screen.getByText('Terminal')).toBeInTheDocument());
  });

  it('"Mark as done" persists and hides the card when everything is done', async () => {
    renderChecklist({ role: 'consumer' });
    fireEvent.click(await screen.findByRole('button', { name: /show the command/i }));
    fireEvent.click(await screen.findByRole('button', { name: /mark as done/i }));
    await waitFor(() => expect(screen.queryByText('Finish setting up')).toBeNull());
  });

  it('dismiss hides the card persistently', async () => {
    const { unmount } = renderChecklist({ role: 'consumer' });
    fireEvent.click(await screen.findByRole('button', { name: /dismiss/i }));
    expect(screen.queryByText('Finish setting up')).toBeNull();
    unmount();
    renderChecklist({ role: 'consumer' });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('Finish setting up')).toBeNull();
  });
});
