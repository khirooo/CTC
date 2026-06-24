import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LandingScreen } from '@/screens/Landing/LandingScreen';

const navigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigate };
});

beforeEach(() => navigate.mockClear());

function renderLanding() {
  return render(
    <MemoryRouter>
      <LandingScreen />
    </MemoryRouter>,
  );
}

describe('LandingScreen', () => {
  it('embeds the how-it-works deck in an iframe', () => {
    renderLanding();
    const frame = screen.getByTitle('How CTC works') as HTMLIFrameElement;
    expect(frame).toBeInTheDocument();
    expect(frame.getAttribute('src')).toBe('/howitworks.html');
  });

  it("routes to the mode-aware /login screen when the deck posts 'ctc:login'", async () => {
    renderLanding();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'ctc:login' } }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/login'));
  });

  it('ignores unrelated postMessages', () => {
    renderLanding();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'something-else' } }));
    expect(navigate).not.toHaveBeenCalled();
  });
});
