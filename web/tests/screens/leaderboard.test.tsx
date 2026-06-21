import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { LeaderboardScreen } from '@/screens/Leaderboard/LeaderboardScreen';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { createMockApi } from '@/api/mockApi';

describe('leaderboard', () => {
  it('renders three tracks', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 'lb.test' });
    await api.signIn('ada@example.com', 'x');
    render(<ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/leaderboard']}>
        <Routes><Route path="/app/leaderboard" element={<LeaderboardScreen />} /></Routes>
      </MemoryRouter></AppProvider></ThemeProvider>);
    await waitFor(() => expect(screen.getByText(/Most generous/i)).toBeInTheDocument());
    expect(screen.getByText(/Top Host \(by usage\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Top Guest/i)).toBeInTheDocument();
  });
});
