import * as vscode from "vscode";
import { ChildProcess, spawn } from "child_process";
import * as path from "path";

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
  const token = await ctx.secrets.get(SECRET_TOKEN);
  if (!token) {
    const pick = await vscode.window.showWarningMessage(
      "No CTC token set. Set it now?", "Set token");
    if (pick === "Set token") {
      await setToken();
    }
    if (!(await ctx.secrets.get(SECRET_TOKEN))) {
      return; // still none — abort
    }
  }

  const cfg = vscode.workspace.getConfiguration();
  let proxyHost = cfg.get<string>("ctc.proxyHost") || "";
  if (!proxyHost) {
    proxyHost = (await vscode.window.showInputBox({
      prompt: "Central CTC proxy host (e.g. ctc.internal)",
      ignoreFocusOut: true,
    })) || "";
    if (!proxyHost) {
      vscode.window.showWarningMessage("CTC not enabled: no proxy host.");
      return;
    }
    await cfg.update("ctc.proxyHost", proxyHost, vscode.ConfigurationTarget.Global);
  }

  const listenPort = cfg.get<number>("ctc.listenPort") ?? 8899;

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

  // Restore the authProvider we cleared, if any.
  const savedAp = ctx.globalState.get<{ existed: boolean; value?: string }>(K_SAVED_AUTHPROVIDER);
  if (savedAp?.existed) {
    const copilotCfg = vscode.workspace.getConfiguration("github.copilot");
    const adv = copilotCfg.inspect<any>("advanced");
    const next = { ...(adv?.globalValue || {}), authProvider: savedAp.value };
    await copilotCfg.update("advanced", next, vscode.ConfigurationTarget.Global);
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
  const token = await ctx.secrets.get(SECRET_TOKEN);
  if (!token) {
    statusItem.text = "$(warning) CTC";
    statusItem.tooltip = "CTC is on but no token is set. Run \"CTC: Set proxy token\".";
    return;
  }
  const cfg = vscode.workspace.getConfiguration();
  const proxyHost = cfg.get<string>("ctc.proxyHost") || "";
  const proxyPort = String(cfg.get<number>("ctc.proxyPort") ?? 8080);
  const listenPort = String(cfg.get<number>("ctc.listenPort") ?? 8899);
  const gheDomain = cfg.get<string>("ctc.gheDomain") || "";

  const shimPath = path.join(ctx.extensionPath, "media", "ctc_ide_shim.py");
  stopShim();
  shim = spawn("python3", [shimPath], {
    env: {
      ...process.env,
      CTC_TOKEN: token,
      CTC_PROXY_HOST: proxyHost,
      CTC_PROXY_PORT: proxyPort,
      CTC_IDE_LISTEN_PORT: listenPort,
      CTC_GHE_DOMAIN: gheDomain,
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
