import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { LandingScreen } from '@/screens/Landing/LandingScreen';
import * as AppCtx from '@/store/AppContext';

beforeEach(() => vi.restoreAllMocks());

describe('LandingScreen', () => {
  function stub() {
    const signIn = vi.fn();
    vi.spyOn(AppCtx, 'useApp').mockReturnValue({ signIn } as any);
    return { signIn };
  }

  it('embeds the how-it-works deck in an iframe', () => {
    stub();
    render(<LandingScreen />);
    const frame = screen.getByTitle('How CTC works') as HTMLIFrameElement;
    expect(frame).toBeInTheDocument();
    expect(frame.getAttribute('src')).toBe('/howitworks.html');
  });

  it("starts OAuth sign-in when the deck posts a 'ctc:login' message", async () => {
    const { signIn } = stub();
    render(<LandingScreen />);
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'ctc:login' } }));
    await waitFor(() => expect(signIn).toHaveBeenCalledOnce());
  });

  it('ignores unrelated postMessages', () => {
    const { signIn } = stub();
    render(<LandingScreen />);
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'something-else' } }));
    expect(signIn).not.toHaveBeenCalled();
  });
});
