import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { MarketplaceScreen } from '@/screens/Marketplace/MarketplaceScreen';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { makeFakeApi } from '../helpers/fakeApi';
import { CtcApiError } from '@/api/http';

async function setup() {
  const api = makeFakeApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'mkt.test' });
  await api.signIn('ada@example.com', 'x');
  render(
    <ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/marketplace']}>
        <Routes><Route path="/app/marketplace" element={<MarketplaceScreen />} /></Routes>
      </MemoryRouter>
    </AppProvider></ThemeProvider>,
  );
  return api;
}

async function setupWithApi(api: ReturnType<typeof makeFakeApi>) {
  render(
    <ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/marketplace']}>
        <Routes><Route path="/app/marketplace" element={<MarketplaceScreen />} /></Routes>
      </MemoryRouter>
    </AppProvider></ThemeProvider>,
  );
}

describe('marketplace', () => {
  it('donates to a request and advances its progress', async () => {
    await setup();
    await waitFor(() => expect(screen.getByText('Lena Hoffmann')).toBeInTheDocument());
    const card = screen.getByText('Lena Hoffmann').closest('[data-request-card]') as HTMLElement;
    expect(within(card).getByText('35.00 AIU / 60.00 AIU')).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: /chip in/i }));
    await waitFor(() => expect(within(card).getByText('60.00 AIU / 60.00 AIU')).toBeInTheDocument());
  });

  it('shows receiver-progress (used vs funded) on a funded request', async () => {
    await setup();
    // Amine's request is fully funded (120) with 72 already burned by the receiver.
    await waitFor(() => expect(screen.getByText('Amine Tazi')).toBeInTheDocument());
    const card = screen.getByText('Amine Tazi').closest('[data-request-card]') as HTMLElement;
    expect(within(card).getByText('used by receiver')).toBeInTheDocument();
    expect(within(card).getByText(/72\.00 AIU \/ 120\.00 AIU · 48\.00 AIU left/)).toBeInTheDocument();
  });

  it('posts a new request', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: /post a request/i }));
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    await waitFor(() => expect(screen.getByText(/All · 7/)).toBeInTheDocument());
  });

  it('fades an expired request and shows the expired pill', async () => {
    await setup();
    // req_6 is expired (5/50 funded, past its deadline).
    await waitFor(() => expect(screen.getByText('Old ask that ran out of time')).toBeInTheDocument());
    const card = screen.getByText('Old ask that ran out of time').closest('[data-request-card]') as HTMLElement;
    expect(card.style.opacity).toBe('0.45');
    expect(within(card).getByText(/✕ expired · never covered/)).toBeInTheDocument();
    // no actions on a dead card
    expect(within(card).queryByRole('button', { name: /chip in/i })).toBeNull();
    expect(within(card).queryByRole('button', { name: /from pool/i })).toBeNull();
    // a live card is not faded
    const live = screen.getByText('Lena Hoffmann').closest('[data-request-card]') as HTMLElement;
    expect(live.style.opacity).toBe('1');
  });

  it('shows the shared pool balance strip', async () => {
    await setup();
    await waitFor(() => expect(screen.getByText(/Shared pool · 500\.00 AIU available/)).toBeInTheDocument());
  });

  it('owner deletes their request and it disappears', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await setup();
    await userEvent.click(screen.getByRole('button', { name: /post a request/i }));
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    await waitFor(() => expect(screen.getByText(/All · 7/)).toBeInTheDocument());
    const own = screen.getByText('your request').closest('[data-request-card]') as HTMLElement;
    await userEvent.click(within(own).getByRole('button', { name: /delete/i }));
    await waitFor(() => expect(screen.getByText(/All · 6/)).toBeInTheDocument());
    expect(screen.queryByText('your request')).toBeNull();
  });

  it('fills own request from the shared pool', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('20');
    await setup();
    await userEvent.click(screen.getByRole('button', { name: /post a request/i }));
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    await waitFor(() => expect(screen.getByText('your request')).toBeInTheDocument());
    const own = screen.getByText('your request').closest('[data-request-card]') as HTMLElement;
    // own card has no personal chip-in, but pool funding is allowed
    expect(within(own).queryByRole('button', { name: /chip in/i })).toBeNull();
    await userEvent.click(within(own).getByRole('button', { name: /from pool/i }));
    await waitFor(() => expect(screen.getByText(/Shared pool · 480\.00 AIU available/)).toBeInTheDocument());
    const updated = screen.getByText('your request').closest('[data-request-card]') as HTMLElement;
    expect(within(updated).getByText(/20\.00 AIU from the shared pool/)).toBeInTheDocument();
  });

  it('shows inline error and does not crash when donate rejects with CtcApiError', async () => {
    const api = makeFakeApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'mkt.err.test' });
    await api.signIn('ada@example.com', 'x');
    const failingApi = Object.assign(Object.create(Object.getPrototypeOf(api)), api, {
      donate: async (_id: string, _amount: number) => {
        throw new CtcApiError('request_closed', 'This request is already closed.', 409);
      },
    });
    await setupWithApi(failingApi as ReturnType<typeof makeFakeApi>);
    await waitFor(() => expect(screen.getByText('Lena Hoffmann')).toBeInTheDocument());
    const card = screen.getByText('Lena Hoffmann').closest('[data-request-card]') as HTMLElement;
    await userEvent.click(within(card).getByRole('button', { name: /chip in/i }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('This request is already closed.'),
    );
    // Screen should still be rendered (no crash)
    expect(screen.getByText('Open requests')).toBeInTheDocument();
  });

  it('shows inline error and does not crash when listRequests rejects with CtcApiError', async () => {
    const api = makeFakeApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'mkt.load.err.test' });
    await api.signIn('ada@example.com', 'x');
    const failingApi = Object.assign(Object.create(Object.getPrototypeOf(api)), api, {
      listRequests: async () => {
        throw new CtcApiError('server_error', 'Service unavailable.', 503);
      },
    });
    await setupWithApi(failingApi as ReturnType<typeof makeFakeApi>);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Service unavailable.'),
    );
    expect(screen.getByText('Open requests')).toBeInTheDocument();
  });
});
