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
    await userEvent.click(screen.getByRole('button', { name: /March 2026/i }));
    // March pledged = 5,400 AIU
    await waitFor(() => expect(screen.getByText('5,400.00 AIU')).toBeInTheDocument());
  });
});
