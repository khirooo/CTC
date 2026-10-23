import { useState } from 'react';
import { TerminalBlock } from './TerminalBlock';

export type InstallOs = 'macos' | 'windows';

/**
 * Best-effort OS guess for the initial tab: Windows if the UA/platform says
 * so, macOS otherwise. CTC does not support Linux, so there is no third
 * option — an unrecognized/absent navigator (e.g. during tests) falls back
 * to macOS.
 */
export function detectInstallOs(): InstallOs {
  if (typeof navigator === 'undefined') return 'macos';
  const probe = `${navigator.userAgent ?? ''} ${navigator.platform ?? ''}`;
  // Match "Windows" (userAgent, e.g. "Windows NT 10.0") or a "Win32"/"Win64"
  // platform string. NOT a bare /win/i — that also matches "darwin" (macOS).
  return /windows|\bwin(32|64)\b/i.test(probe) ? 'windows' : 'macos';
}

const WINDOWS_CAPTION = 'Paste in PowerShell and press Enter, then type ctc to start.';
const WINDOWS_CERT_NOTE = 'Windows will ask you to confirm installing the CTC certificate — click Yes.';
const WINDOWS_POLICY_NOTE =
  'If PowerShell says "running scripts is disabled", run once: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned — then paste the command again.';

interface InstallCommandProps {
  commandMac: string;
  commandWindows: string;
  /** Caption shown under the macOS command. The Windows command always shows
   *  its own fixed caption plus a certificate-trust note (see WINDOWS_CAPTION
   *  / WINDOWS_CERT_NOTE above) — Windows trust works differently enough
   *  (its own confirmation dialog) that it needs its own wording everywhere
   *  this component is used. */
  captionMac?: string;
  style?: React.CSSProperties;
}

/**
 * Install one-liner with an OS switch (macOS / Windows) above a TerminalBlock
 * showing the command for the selected OS. Defaults to the OS the browser
 * reports, but the user can flip it (e.g. copying the Windows command from a
 * Mac for a teammate). Shared by Onboarding, Profile, and the dashboard
 * SetupChecklist so the two one-liners only need to be composed in one place.
 */
export function InstallCommand({ commandMac, commandWindows, captionMac, style }: InstallCommandProps) {
  const [os, setOs] = useState<InstallOs>(detectInstallOs);

  function tabStyle(active: boolean): React.CSSProperties {
    return {
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 12,
      fontWeight: 600,
      padding: '6px 14px',
      borderRadius: 8,
      border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
      background: active ? 'var(--accent-soft)' : 'var(--surface-2)',
      color: active ? 'var(--accent)' : 'var(--text-dim)',
      cursor: 'pointer',
    };
  }

  return (
    <div style={style}>
      <div role="tablist" aria-label="Operating system" style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button
          type="button"
          role="tab"
          aria-selected={os === 'macos'}
          onClick={() => setOs('macos')}
          style={tabStyle(os === 'macos')}
        >
          macOS
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={os === 'windows'}
          onClick={() => setOs('windows')}
          style={tabStyle(os === 'windows')}
        >
          Windows
        </button>
      </div>
      <TerminalBlock
        command={os === 'macos' ? commandMac : commandWindows}
        caption={os === 'macos' ? captionMac : WINDOWS_CAPTION}
      />
      {os === 'windows' && (
        <p style={{ fontSize: 11, color: 'var(--text-faint)', margin: '8px 2px 0', lineHeight: 1.5 }}>
          {WINDOWS_CERT_NOTE}
          <br />
          {WINDOWS_POLICY_NOTE}
        </p>
      )}
    </div>
  );
}
