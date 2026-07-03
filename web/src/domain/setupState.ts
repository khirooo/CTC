/**
 * Per-user client-side setup progress. Frontend-only by design (spec §2):
 * the server can't verify a terminal install, so "I ran it" acknowledgments,
 * checklist dismissal, and the first-run tour flag live in localStorage.
 * Server truth (session.hasPat) is always re-derived by callers and never
 * stored here.
 */
export interface SetupState {
  /** User confirmed they ran the CLI install command. */
  installAck: boolean;
  /** User dismissed the dashboard "Finish setting up" card. */
  checklistDismissed: boolean;
  /** First-run spotlight tour completed or skipped. */
  tourDone: boolean;
}

const DEFAULTS: SetupState = { installAck: false, checklistDismissed: false, tourDone: false };

const key = (userId: string) => `ctc:setup:${userId}`;

export function loadSetupState(userId: string): SetupState {
  try {
    const raw = localStorage.getItem(key(userId));
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<SetupState>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSetupState(userId: string, patch: Partial<SetupState>): SetupState {
  const next = { ...loadSetupState(userId), ...patch };
  try {
    localStorage.setItem(key(userId), JSON.stringify(next));
  } catch {
    // localStorage unavailable (private browsing) — state is session-only.
  }
  return next;
}
