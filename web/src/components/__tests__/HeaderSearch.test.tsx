import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { HeaderSearch } from '@/components/HeaderSearch';

const api = { searchUsers: vi.fn(async (q: string) => q ? [{ id: 'u1', name: 'Alice', login: 'alice', initials: 'A', role: 'giver' as const }] : []) };

describe('HeaderSearch', () => {
  it('queries on input and shows hits; renders nothing for blank', async () => {
    render(<MemoryRouter><HeaderSearch api={api as any} /></MemoryRouter>);
    const input = screen.getByPlaceholderText(/search/i);
    await userEvent.type(input, 'al');
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument());
    await userEvent.clear(input);
    await waitFor(() => expect(screen.queryByText('Alice')).not.toBeInTheDocument());
  });
});
