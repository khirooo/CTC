import { describe, it, expect, beforeEach } from 'vitest';
import { loadSetupState, saveSetupState } from '@/domain/setupState';

describe('setupState', () => {
  beforeEach(() => localStorage.clear());

  it('defaults to all-false for an unknown user', () => {
    expect(loadSetupState('u1')).toEqual({ installAck: false, checklistDismissed: false, tourDone: false });
  });

  it('persists a patch and merges with existing state', () => {
    saveSetupState('u1', { installAck: true });
    saveSetupState('u1', { tourDone: true });
    expect(loadSetupState('u1')).toEqual({ installAck: true, checklistDismissed: false, tourDone: true });
  });

  it('keys state per user', () => {
    saveSetupState('u1', { installAck: true });
    expect(loadSetupState('u2').installAck).toBe(false);
  });

  it('survives corrupt stored JSON', () => {
    localStorage.setItem('ctc:setup:u1', '{nope');
    expect(loadSetupState('u1')).toEqual({ installAck: false, checklistDismissed: false, tourDone: false });
  });
});
