import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { HistoryScreen } from '@/screens/History/HistoryScreen';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { makeFakeApi } from '../helpers/fakeApi';

describe('history', () => {
  it('switches the selected month', async () => {
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'hist.test' });
    await api.signIn('ada@example.com', 'x');
    render(<ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/history']}>
        <Routes><Route path="/app/history" element={<HistoryScreen />} /></Routes>
      </MemoryRouter></AppProvider></ThemeProvider>);
    await waitFor(() => expect(screen.getByRole('button', { name: /May 2026/i })).toBeInTheDocument());
    // Scalable cycle rail (a list, not a fixed button set) is labelled and counts cycles.
    expect(screen.getByText('Cycles')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /March 2026/i }));
    // March pledged = 5,400 AIU
    await waitFor(() => expect(screen.getByText('5,400.00 AIU')).toBeInTheDocument());
  });

  it('shows an empty state when there are no closed cycles', async () => {
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'hist.empty' });
    await api.signIn('ada@example.com', 'x');
    api.getHistory = (async () => []) as typeof api.getHistory;
    render(<ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/history']}>
        <Routes><Route path="/app/history" element={<HistoryScreen />} /></Routes>
      </MemoryRouter></AppProvider></ThemeProvider>);
    await waitFor(() => expect(screen.getByText(/no closed cycles yet/i)).toBeInTheDocument());
    // No cycle rail when there's nothing to show.
    expect(screen.queryByText('Cycles')).toBeNull();
  });

  it('shows euro conversions for routed/transferred/unused budget', async () => {
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'hist.eur' });
    await api.signIn('ada@example.com', 'x');
    render(<ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/history']}>
        <Routes><Route path="/app/history" element={<HistoryScreen />} /></Routes>
      </MemoryRouter></AppProvider></ThemeProvider>);
    // May 2026 (default selected): routed to Hosts + transferred to Guests + unused budget
    // each render a "≈ €…" conversion line.
    await waitFor(() => expect(screen.getByText(/routed to Hosts/i)).toBeInTheDocument());
    expect(screen.getByText(/transferred to Guests/i)).toBeInTheDocument();
    expect(screen.getAllByText(/≈ €/).length).toBeGreaterThanOrEqual(3);
  });
});
