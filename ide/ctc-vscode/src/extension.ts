import * as vscode from "vscode";
import { ChildProcess, spawn } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// Config read from ~/.config/ctc/env (written by `ctc login`) so a user who ran
// the installer needs zero manual VS Code setup — token, proxy, and GHE domain
// all come from there. VS Code settings / SecretStorage override it when present.
interface CtcEnv {
  token?: string;
  host?: string;
  port?: number;
  domain?: string;
}

function readCtcEnvFile(): CtcEnv {
  try {
    const base = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
    const text = fs.readFileSync(path.join(base, "ctc", "env"), "utf8");
    const get = (k: string): string | undefined => {
      const m = text.match(new RegExp(`^\\s*export\\s+${k}="?([^"\\n]*)"?\\s*$`, "m"));
      return m ? m[1] : undefined;
    };
    const out: CtcEnv = { token: get("COPILOT_GITHUB_TOKEN"), domain: get("GH_HOST") };
    const hp = get("HTTPS_PROXY");
    if (hp) {
      const m = hp.match(/https?:\/\/([^:/]+)(?::(\d+))?/);
      if (m) {
        out.host = m[1];
        out.port = m[2] ? parseInt(m[2], 10) : 8080;
      }
    }
    return out;
  } catch {
    return {};
  }
}

interface EffConfig {
  token?: string;
  host?: string;
  port: number;
  listenPort: number;
  domain: string;
}

async function effectiveConfig(): Promise<EffConfig> {
  const env = readCtcEnvFile();
  const cfg = vscode.workspace.getConfiguration();
  return {
    token: (await ctx.secrets.get(SECRET_TOKEN)) || env.token,
    host: (cfg.get<string>("ctc.proxyHost") || "") || env.host,
    port: cfg.get<number>("ctc.proxyPort") ?? env.port ?? 8080,
    listenPort: cfg.get<number>("ctc.listenPort") ?? 8899,
    domain: (cfg.get<string>("ctc.gheDomain") || "") || env.domain || "",
  };
}

// globalState keys
const K_ENABLED = "ctc.enabled";
const K_SAVED_PROXY = "ctc.savedHttpProxy"; // { existed: boolean, value?: string }
const K_SAVED_AUTHPROVIDER = "ctc.savedAuthProvider"; // { existed: boolean, value?: string }
const SECRET_TOKEN = "ctc.token";

let statusItem: vscode.StatusBarItem;
let shim: ChildProcess | undefined;
let ctx: vscode.ExtensionContext;

export function activate(context: vscode.ExtensionContext) {
  ctx = context;

  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "ctc.toggle";
  context.subscriptions.push(statusItem);

  context.subscriptions.push(
    vscode.commands.registerCommand("ctc.toggle", toggle),
    vscode.commands.registerCommand("ctc.setToken", setToken),
  );

  refreshStatus();
  if (isEnabled()) {
    // Post-reload: CTC mode is on, so (re)start the shim for this window.
    void startShim();
  }
}

export function deactivate() {
  stopShim();
}

// ── state helpers ────────────────────────────────────────────────────────────

function isEnabled(): boolean {
  return ctx.globalState.get<boolean>(K_ENABLED) === true;
}

function refreshStatus() {
  const on = isEnabled();
  statusItem.text = on ? "$(circle-filled) CTC" : "$(circle-outline) CTC";
  statusItem.tooltip = on
    ? "CTC mode is ON — Copilot bills the shared pool. Click to turn off."
    : "CTC mode is OFF — normal Copilot. Click to route Copilot through CTC.";
  statusItem.show();
}

// ── commands ─────────────────────────────────────────────────────────────────

async function toggle() {
  if (isEnabled()) {
    await disable();
  } else {
    await enable();
  }
}

async function setToken() {
  const token = await vscode.window.showInputBox({
    prompt: "Paste your CTC proxy token (from the dashboard \"Set up CLI\" panel)",
    password: true,
    ignoreFocusOut: true,
  });
  if (token && token.trim()) {
    await ctx.secrets.store(SECRET_TOKEN, token.trim());
    vscode.window.showInformationMessage("CTC token saved.");
  }
}

// ── enable / disable ─────────────────────────────────────────────────────────

async function enable() {
  let eff = await effectiveConfig();

  if (!eff.token) {
    const pick = await vscode.window.showWarningMessage(
      "No CTC token found (run the installer / `ctc login`, or set it here).",
      "Set token");
    if (pick === "Set token") {
      await setToken();
    }
    eff = await effectiveConfig();
    if (!eff.token) {
      return; // still none — abort
    }
  }

  if (!eff.host) {
    const cfg = vscode.workspace.getConfiguration();
    const host = (await vscode.window.showInputBox({
      prompt: "Central CTC proxy host (e.g. ctc.internal)",
      ignoreFocusOut: true,
    })) || "";
    if (!host) {
      vscode.window.showWarningMessage("CTC not enabled: no proxy host.");
      return;
    }
    await cfg.update("ctc.proxyHost", host, vscode.ConfigurationTarget.Global);
    eff = await effectiveConfig();
  }

  const listenPort = eff.listenPort;

  // Save the user's current http.proxy so we can restore it on disable.
  const httpCfg = vscode.workspace.getConfiguration("http");
  const curProxy = httpCfg.inspect<string>("proxy");
  await ctx.globalState.update(K_SAVED_PROXY, {
    existed: curProxy?.globalValue !== undefined,
    value: curProxy?.globalValue,
  });

  await httpCfg.update("proxy", `http://127.0.0.1:${listenPort}`, vscode.ConfigurationTarget.Global);
  await httpCfg.update("proxyStrictSSL", false, vscode.ConfigurationTarget.Global);
  await httpCfg.update("proxySupport", "on", vscode.ConfigurationTarget.Global);

  // Clear the github-enterprise authProvider conflict (breaks the CTC path).
  // Best-effort: writing another extension's config can fail if it isn't
  // registered — never let that abort the toggle.
  try {
    const copilotCfg = vscode.workspace.getConfiguration("github.copilot");
    const adv = copilotCfg.inspect<any>("advanced");
    const advVal = adv?.globalValue;
    const authProvider = advVal && typeof advVal === "object" ? advVal.authProvider : undefined;
    if (authProvider === "github-enterprise") {
      await ctx.globalState.update(K_SAVED_AUTHPROVIDER, { existed: true, value: authProvider });
      const next = { ...advVal };
      delete next.authProvider;
      await copilotCfg.update("advanced", next, vscode.ConfigurationTarget.Global);
    } else {
      await ctx.globalState.update(K_SAVED_AUTHPROVIDER, { existed: false });
    }
  } catch {
    await ctx.globalState.update(K_SAVED_AUTHPROVIDER, { existed: false });
    vscode.window.showWarningMessage(
      "CTC couldn't adjust github.copilot.advanced automatically. If Copilot chat "
      + "says \"Authorization failed\", remove \"authProvider\": \"github-enterprise\" "
      + "from github.copilot.advanced in settings.json.");
  }

  await ctx.globalState.update(K_ENABLED, true);
  await reload("CTC mode ON — reloading. After reload, use Copilot normally; it bills the pool.");
}

async function disable() {
  const httpCfg = vscode.workspace.getConfiguration("http");
  const saved = ctx.globalState.get<{ existed: boolean; value?: string }>(K_SAVED_PROXY);
  await httpCfg.update(
    "proxy",
    saved?.existed ? saved.value : undefined,
    vscode.ConfigurationTarget.Global,
  );
  // Remove our strictSSL/proxySupport overrides.
  await httpCfg.update("proxyStrictSSL", undefined, vscode.ConfigurationTarget.Global);
  await httpCfg.update("proxySupport", undefined, vscode.ConfigurationTarget.Global);

  // Restore the authProvider we cleared, if any (best-effort).
  const savedAp = ctx.globalState.get<{ existed: boolean; value?: string }>(K_SAVED_AUTHPROVIDER);
  if (savedAp?.existed) {
    try {
      const copilotCfg = vscode.workspace.getConfiguration("github.copilot");
      const adv = copilotCfg.inspect<any>("advanced");
      const next = { ...(adv?.globalValue || {}), authProvider: savedAp.value };
      await copilotCfg.update("advanced", next, vscode.ConfigurationTarget.Global);
    } catch {
      // ignore — user can restore manually
    }
  }

  await ctx.globalState.update(K_ENABLED, false);
  stopShim();
  await reload("CTC mode OFF — reloading. Normal Copilot restored.");
}

async function reload(message: string) {
  refreshStatus();
  vscode.window.showInformationMessage(message);
  await vscode.commands.executeCommand("workbench.action.reloadWindow");
}

// ── shim lifecycle ───────────────────────────────────────────────────────────

async function startShim() {
  const eff = await effectiveConfig();
  if (!eff.token) {
    statusItem.text = "$(warning) CTC";
    statusItem.tooltip = "CTC is on but no token found. Run the installer / `ctc login`, "
      + "or \"CTC: Set proxy token\".";
    return;
  }

  const shimPath = path.join(ctx.extensionPath, "media", "ctc_ide_shim.py");
  stopShim();
  shim = spawn("python3", [shimPath], {
    env: {
      ...process.env,
      CTC_TOKEN: eff.token,
      CTC_PROXY_HOST: eff.host || "",
      CTC_PROXY_PORT: String(eff.port),
      CTC_IDE_LISTEN_PORT: String(eff.listenPort),
      CTC_GHE_DOMAIN: eff.domain,
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  shim.on("error", (err) => {
    statusItem.text = "$(error) CTC";
    statusItem.tooltip = `CTC shim failed to start: ${err.message}. Is python3 on PATH?`;
  });
  shim.on("exit", (code) => {
    if (isEnabled() && code !== 0 && code !== null) {
      statusItem.text = "$(error) CTC";
      statusItem.tooltip = `CTC shim exited (code ${code}). Toggle off/on to retry.`;
    }
  });
}

function stopShim() {
  if (shim) {
    try {
      shim.kill();
    } catch {
      // ignore
    }
    shim = undefined;
  }
}
