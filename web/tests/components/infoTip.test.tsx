import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { InfoTip } from '@/components/InfoTip';
import { glossary } from '@/domain/glossary';

describe('InfoTip', () => {
  it('renders a labelled trigger and no popover initially', () => {
    render(<InfoTip term="credits" />);
    expect(screen.getByRole('button', { name: 'About Credits' })).toBeInTheDocument();
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('opens on click showing the glossary body, closes on Escape', () => {
    render(<InfoTip term="pool" />);
    fireEvent.click(screen.getByRole('button', { name: 'About Shared pool' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent(glossary.pool.body);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('supports custom title/body without a term', () => {
    render(<InfoTip title="Custom" body="Custom explanation here." />);
    fireEvent.click(screen.getByRole('button', { name: 'About Custom' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Custom explanation here.');
  });
});
