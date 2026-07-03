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

  it('stays open on a fresh click, which the browser fires as focus then click', () => {
    render(<InfoTip term="pool" />);
    const button = screen.getByRole('button', { name: 'About Shared pool' });
    // Real browsers fire `focus` before `click` on a mouse/tap click of an
    // unfocused button. If the click handler toggles instead of forcing
    // open, this sequence would open then immediately close the popover.
    fireEvent.focus(button);
    fireEvent.click(button);
    expect(screen.getByRole('tooltip')).toHaveTextContent(glossary.pool.body);
  });

  it('does not close when clicked again while already open via hover', () => {
    render(<InfoTip term="pool" />);
    const button = screen.getByRole('button', { name: 'About Shared pool' });
    const root = button.parentElement as HTMLElement;
    fireEvent.mouseEnter(root);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
  });

  it('portals the popover to document.body so ancestor overflow/stacking cannot clip it', () => {
    render(<InfoTip term="pool" />);
    fireEvent.click(screen.getByRole('button', { name: 'About Shared pool' }));
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip.parentElement).toBe(document.body);
  });
});
