---
name: frontend-stuck-loading-diagnosis
description: This skill should be used when a user reports that a web app or PWA page is stuck on a loading spinner or a "加载中"/"分析中" message. It provides a workflow to locate the exact stuck point, reproduce it in a real browser, identify the blocking network call, and fix it with timeout and domestic-reachable fallback strategies.
agent_created: true
---

# Frontend Stuck Loading Diagnosis

## When to use

Use this skill when:
- A web app or PWA shows a permanent loading spinner or "加载中"/"分析中" text.
- Previous fixes targeted the wrong area (e.g., list loading) while the user's complaint actually points to a detail overlay or another section.
- Network calls to foreign services such as GitHub, Gist, or gist.githubusercontent.com may be blocked or slow on the user's real device.

## Diagnostic workflow

### 1. Locate the exact loading文案 source

- Grep the codebase for the exact user-reported loading text (for example, "加载分析数据", "分析中", "正在扫描").
- Identify which function or component renders that text; this is the real stuck point, not just the general page initialization.
- Read the surrounding function to see which async calls are awaited before the spinner is replaced.

### 2. Identify the blocking call

- Look for `await fetch(...)` calls that hit blocked or slow domains (such as gist.githubusercontent.com, api.github.com, raw.githubusercontent.com) without an `AbortController` timeout.
- Check `Content-Security-Policy` to see whether the target domain is allowed in `connect-src` or `script-src`.
- Confirm whether the call is on the critical rendering path or is only an optional enhancement.

### 3. Reproduce in a real browser

- Start a local static server for the project, for example `python -m http.server 8899 --directory <project>`.
- Use `agent-browser` to open the page and take a screenshot or snapshot after a realistic wait.
- On Windows, if PowerShell blocks `agent-browser.ps1`, run `Set-ExecutionPolicy -Scope Process Bypass -Force` first.
- Verify that the spinner is still present; this confirms the bug is not just a curl/Node artifact.

### 4. Fix the root cause

- Remove the blocking call from the critical path; do not `await` a blocked or unreliable service before rendering.
- Replace it with a domestic-reachable fallback (for example, Tencent JSONP for K-line data, or `qt.gtimg.cn` for stock quotes).
- Add `AbortController` timeouts to all remaining `fetch` and JSONP requests; 8–15 seconds is usually enough for mobile.
- Make fav/sync operations non-blocking in `init()` so they cannot stall the main UI.
- If the page is a PWA, bump the Service Worker `CACHE_NAME` so existing clients update to the new code.

### 5. Validate and deploy

- Run syntax checks on inline scripts (for example, extract `<script>` blocks and run `new vm.Script(code)` in Node).
- Re-run the real-browser test and confirm the spinner disappears and real content renders.
- Deploy via CloudStudio or the project's usual host, and tell the user to hard-refresh or clear cache once.

## Common pitfalls

- Do not rely solely on `curl` or Node tests; browsers enforce CSP and may behave differently from shell tools.
- A successful HTTP 200 from `curl` does not mean the browser can use the same URL.
- Retries against a blocked domain usually just waste time; removing or isolating the blocking call is often better.
