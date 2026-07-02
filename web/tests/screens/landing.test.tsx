import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LandingScreen } from '@/screens/Landing/LandingScreen';
import { useApp } from '@/store/AppContext';

const signIn = vi.fn();
vi.mock('@/store/AppContext', () => ({ useApp: vi.fn() }));

beforeEach(() => {
  signIn.mockClear();
  vi.mocked(useApp).mockReturnValue({ signIn } as unknown as ReturnType<typeof useApp>);
});

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

  it("starts GitLab OAuth directly when the deck posts 'ctc:login'", async () => {
    renderLanding();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'ctc:login' } }));
    await waitFor(() => expect(signIn).toHaveBeenCalled());
  });

  it('ignores unrelated postMessages', () => {
    renderLanding();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'something-else' } }));
    expect(signIn).not.toHaveBeenCalled();
  });
});
