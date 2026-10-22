import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InstallCommand, detectInstallOs } from '@/components/InstallCommand';

afterEach(() => {
  vi.restoreAllMocks();
});

function mockUserAgent(ua: string) {
  vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(ua);
}

const MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36';
const WIN_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36';

describe('detectInstallOs', () => {
  it('returns macos for a macOS user agent', () => {
    mockUserAgent(MAC_UA);
    expect(detectInstallOs()).toBe('macos');
  });

  it('returns windows for a Windows user agent', () => {
    mockUserAgent(WIN_UA);
    expect(detectInstallOs()).toBe('windows');
  });
});

describe('InstallCommand', () => {
  it('renders an accessible OS tablist defaulting to macOS, showing the macOS command', () => {
    mockUserAgent(MAC_UA);
    render(
      <InstallCommand
        commandMac="curl -fsSL https://ctc.local/install.sh | sh -s -- --token tok"
        commandWindows='curl.exe -fsSLko "$env:TEMP\ctc-install.ps1" https://ctc.local/install.ps1; powershell -NoProfile -File "$env:TEMP\ctc-install.ps1" -Token tok'
        captionMac="macOS caption"
      />,
    );
    expect(screen.getByRole('tablist', { name: /operating system/i })).toBeInTheDocument();
    const macTab = screen.getByRole('tab', { name: 'macOS' });
    const winTab = screen.getByRole('tab', { name: 'Windows' });
    expect(macTab).toHaveAttribute('aria-selected', 'true');
    expect(winTab).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByText(/--token tok/)).toBeInTheDocument();
    expect(screen.getByText('macOS caption')).toBeInTheDocument();
    expect(screen.queryByText(/certificate/i)).not.toBeInTheDocument();
  });

  it('defaults to Windows when the UA reports Windows, and shows the cert-trust note', () => {
    mockUserAgent(WIN_UA);
    render(
      <InstallCommand
        commandMac="curl -fsSL https://ctc.local/install.sh | sh -s -- --token tok"
        commandWindows='curl.exe -fsSLko "$env:TEMP\ctc-install.ps1" https://ctc.local/install.ps1; powershell -NoProfile -File "$env:TEMP\ctc-install.ps1" -Token tok'
        captionMac="macOS caption"
      />,
    );
    const winTab = screen.getByRole('tab', { name: 'Windows' });
    expect(winTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/-Token tok/)).toBeInTheDocument();
    expect(screen.getByText(/Paste in PowerShell and press Enter/)).toBeInTheDocument();
    expect(screen.getByText(/confirm installing the CTC certificate/i)).toBeInTheDocument();
    expect(screen.getByText(/Set-ExecutionPolicy -Scope CurrentUser RemoteSigned/)).toBeInTheDocument();
    expect(screen.queryByText(/Bypass/)).not.toBeInTheDocument();
  });

  it('switching tabs swaps the displayed command', async () => {
    mockUserAgent(MAC_UA);
    render(
      <InstallCommand
        commandMac="curl -fsSL https://ctc.local/install.sh | sh -s -- --token tok"
        commandWindows='curl.exe -fsSLko "$env:TEMP\ctc-install.ps1" https://ctc.local/install.ps1; powershell -NoProfile -File "$env:TEMP\ctc-install.ps1" -Token tok'
        captionMac="macOS caption"
      />,
    );
    await userEvent.click(screen.getByRole('tab', { name: 'Windows' }));
    expect(screen.getByRole('tab', { name: 'Windows' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/-Token tok/)).toBeInTheDocument();
    expect(screen.queryByText(/--token tok/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'macOS' }));
    expect(screen.getByRole('tab', { name: 'macOS' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/--token tok/)).toBeInTheDocument();
  });
});
