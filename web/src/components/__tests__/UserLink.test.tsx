import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { UserLink } from '@/components/UserLink';

describe('UserLink', () => {
  it('navigates to the user profile on click', async () => {
    render(
      <MemoryRouter initialEntries={['/app/leaderboard']}>
        <Routes>
          <Route path="/app/leaderboard" element={<UserLink userId="u1" name="Alice" />} />
          <Route path="/app/users/:id" element={<div>profile u1</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByText('Alice'));
    expect(screen.getByText('profile u1')).toBeInTheDocument();
  });

  it('renders a plain span (no link) when userId is null', async () => {
    render(
      <MemoryRouter initialEntries={['/app/leaderboard']}>
        <Routes>
          <Route path="/app/leaderboard" element={<UserLink userId={null} name="Nobody" />} />
          <Route path="/app/users/:id" element={<div>should not reach</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const el = screen.getByText('Nobody');
    // Not a link/button — no navigation affordance for a null user.
    expect(el.getAttribute('role')).toBeNull();
    expect(el.tagName).toBe('SPAN');
    await userEvent.click(el);
    expect(screen.queryByText('should not reach')).toBeNull();
  });
});
