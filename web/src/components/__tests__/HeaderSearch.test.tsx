import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { HeaderSearch } from '@/components/HeaderSearch';

const api = { searchUsers: vi.fn(async (q: string) => q ? [{ id: 'u1', name: 'Alice', login: 'alice', initials: 'A', role: 'giver' as const }] : []) };

const hit = (id: string, name: string) => ({ id, name, login: name.toLowerCase(), initials: name[0], role: 'giver' as const });

describe('HeaderSearch', () => {
  it('queries on input and shows hits; renders nothing for blank', async () => {
    render(<MemoryRouter><HeaderSearch api={api as any} /></MemoryRouter>);
    const input = screen.getByPlaceholderText(/search/i);
    await userEvent.type(input, 'al');
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument());
    await userEvent.clear(input);
    await waitFor(() => expect(screen.queryByText('Alice')).not.toBeInTheDocument());
  });

  it('ignores a slow stale response so the newest query wins', async () => {
    vi.useFakeTimers();
    try {
      const resolvers: Record<string, (v: unknown) => void> = {};
      const raceApi = {
        searchUsers: vi.fn((q: string) => new Promise((res) => { resolvers[q] = res; })),
      };
      render(<MemoryRouter><HeaderSearch api={raceApi as any} /></MemoryRouter>);
      const input = screen.getByPlaceholderText(/search/i);

      fireEvent.change(input, { target: { value: 'a' } });
      act(() => { vi.advanceTimersByTime(250); });   // fires searchUsers('a')
      fireEvent.change(input, { target: { value: 'ab' } });
      act(() => { vi.advanceTimersByTime(250); });   // fires searchUsers('ab')

      // Newest query resolves first, then the stale older one.
      await act(async () => { resolvers['ab']([hit('u2', 'Bob')]); });
      await act(async () => { resolvers['a']([hit('u1', 'Alice')]); });

      expect(screen.getByText('Bob')).toBeInTheDocument();
      expect(screen.queryByText('Alice')).toBeNull();  // stale response discarded
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders result rows as focusable buttons (keyboard a11y)', async () => {
    render(<MemoryRouter><HeaderSearch api={api as any} /></MemoryRouter>);
    await userEvent.type(screen.getByPlaceholderText(/search/i), 'al');
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument());
    const row = screen.getByText('Alice').closest('button');
    expect(row).not.toBeNull();
  });
});
