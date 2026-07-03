import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Tour } from '@/components/Tour';

function Anchors() {
  return (
    <>
      <nav data-tour="nav">nav</nav>
      <div data-tour="cycle-banner">banner</div>
      <div data-tour="stats">stats</div>
      {/* marketplace-hero + setup-checklist intentionally absent → steps skipped */}
    </>
  );
}

describe('Tour', () => {
  it('renders nothing when closed', () => {
    render(<><Anchors /><Tour open={false} onClose={() => {}} /></>);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('walks present targets and skips missing ones', () => {
    const onClose = vi.fn();
    render(<><Anchors /><Tour open onClose={onClose} /></>);
    expect(screen.getByRole('dialog')).toHaveTextContent('The screens');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Cycle');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Credits');
    // marketplace-hero and setup-checklist are missing → tour ends
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('skip closes immediately', () => {
    const onClose = vi.fn();
    render(<><Anchors /><Tour open onClose={onClose} /></>);
    fireEvent.click(screen.getByRole('button', { name: 'Skip tour' }));
    expect(onClose).toHaveBeenCalled();
  });
});
