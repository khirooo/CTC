import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppRoutes } from '@/app/routes';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { makeFakeApi } from '../helpers/fakeApi';

function renderAt(path: string) {
  const api = makeFakeApi({ latencyMs: 0, storageKey: 'routes.' + path });
  return render(
    <ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter>
    </AppProvider></ThemeProvider>,
  );
}

describe('routes', () => {
  it('redirects unauthenticated /app/dashboard to the landing page', async () => {
    renderAt('/app/dashboard');
    await waitFor(() => expect(screen.getByTitle('How CTC works')).toBeInTheDocument());
  });
  it('redirects the old /signin path to the mode-aware /login screen', async () => {
    renderAt('/signin');
    await waitFor(() => expect(screen.getByText('Welcome to CTC')).toBeInTheDocument());
  });
  it('serves the mode-aware login screen at /login', async () => {
    renderAt('/login');
    await waitFor(() => expect(screen.getByText('Welcome to CTC')).toBeInTheDocument());
  });
});
