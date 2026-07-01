import { describe, it, expect } from 'vitest';
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
    await waitFor(() => expect(screen.getByText(/All · 6/)).toBeInTheDocument());
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
