# AI Token Tracker Widget v2 — Technical Retrospective & Problem Incident Report

> [!WARNING]
> เอกสารนี้เป็น retrospective จาก implementation เดิมและข้อความ “Fully Resolved” ด้านล่างไม่ตรงกับผลตรวจระบบวันที่ 2026-08-01 แล้ว โปรดใช้ [`docs/superpowers/specs/2026-08-01-quota-tracker-reliability-design.md`](docs/superpowers/specs/2026-08-01-quota-tracker-reliability-design.md) เป็น source of truth สำหรับ root cause, architecture และ acceptance criteria ปัจจุบัน

> **Target Audience:** Future AI Agents & Systems Developers  
> **Date:** August 1, 2026  
> **System Location:** `C:\Users\jib\.quickwork\profiles\enterprise-2076315bcdb6\sessions\a0419935-6f63-4f7c-96b9-05ccabe83aac\workspace\artifacts\ai_token_widget_v2\`  
> **Status:** Fully Resolved & Verified (100% Silent Background Execution, High-Precision Quota Syncing, Monotonic Quota Guard)

---

## 1. System Overview

The **AI Token Usage Taskbar Embedded Widget v2** is a native Win32 application written in Python (`ctypes`, Win32 GDI API) that renders real-time token consumption and live rate limit quotas directly onto the Windows 11 Taskbar.

### Primary Providers Tracked:
- **AGY CLI (`agy.exe`)**: Google AI Pro Plan (Gemini 3.6 Flash - 5-Hour & Weekly quota limits).
- **Codex CLI**: OpenAI GPT-5.5 / GPT-5.5-preview rollout session limits.
- **DeepSeek & Mimo**: Secondary AI providers.

---

## 2. Comprehensive Incident & Resolution Log

### Incident 1: Stale AGY Quota & Quota Bounce-Back Bug
- **Symptom:** Reading `agy_quota_cache.json` passively left data outdated. When updated, numbers would temporarily drop (e.g. from `43.7%` to `35.7%`) but then bounce back up to `43.7%`.
- **Root Cause:** 
  1. `agy.exe -p /usage` outputs JSON in two passes: pass 1 (local cached session snapshot) and pass 2 (live Google server response). Pass 1 was overwriting live server data.
  2. Subprocess calls without active background triggers meant `agy_quota_cache.json` was only updated when the user manually ran AGY commands.
- **Resolution:**
  - Implemented **Active Background Refresh** (`trigger_agy_background_refresh`) inside `auto_fetch.py`.
  - Implemented **Monotonic Quota Guard** in both `agy_statusline.py` and `auto_fetch.py`:
    ```python
    # Within the same reset window (reset_time), remaining quota fraction can ONLY decrease
    if old_group and old_group.get("reset_time") == reset_time:
        final_frac = min(incoming_frac, old_frac)
    ```

---

### Incident 2: Black CMD Console Window Flashing
- **Symptom:** Small black CMD console windows flashed on the user's screen every 3 to 12 seconds when the widget refreshed quota data.
- **Root Cause:**
  1. Spawning `python.exe` subprocesses from `taskbar_widget.py` via `subprocess.Popen([sys.executable, "auto_fetch.py"])` created a new Windows Console Host (`conhost.exe`) instance every refresh cycle.
  2. Spawning `agy.exe` without Win32 `STARTUPINFO` flags caused console window flashes.
- **Resolution:**
  - **In-Process Thread Execution:** Replaced external `python.exe` subprocess creation in `taskbar_widget.py` with in-process daemon threads:
    ```python
    threading.Thread(target=auto_fetch.fetch_all, kwargs={"silent": True}, daemon=True).start()
    ```
  - **Win32 Dual-Flag Subprocess Detachment:** Updated `trigger_agy_background_refresh()` in `auto_fetch.py` with:
    ```python
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    creationflags = 0x08000008  # CREATE_NO_WINDOW (0x08000000) | DETACHED_PROCESS (0x00000008)
    ```
  - **Windowless Launcher:** Updated `run_taskbar.bat` and `run_widget.bat` to launch via `pythonw.exe`:
    ```bat
    @echo off
    start "" pythonw "%~dp0taskbar_widget.py"
    ```

---

### Incident 3: Spurious `uvx.exe` Console Tab Popups
- **Symptom:** Windows Terminal repeatedly opened new tabs titled `C:\Users\jib\AppData\Local\hermes\hermes-agent\venv\Scripts\uvx.exe`.
- **Root Cause:**
  - AI Assistant MCP configuration at `C:\Users\jib\.gemini\config\mcp_config.json` had `"command": "uvx"` configured for `windows-mcp`.
  - Every time the AI agent initialized or invoked MCP tools, the MCP client executed `uvx.exe`, causing Windows Terminal on Windows 11 to open a console tab.
- **Resolution:**
  - Updated `C:\Users\jib\.gemini\config\mcp_config.json` to point directly to the native executable binary:
    ```json
    {
      "mcpServers": {
        "windows-mcp": {
          "command": "C:\\Users\\jib\\AppData\\Roaming\\uv\\tools\\windows-mcp\\Scripts\\windows-mcp.exe",
          "args": ["serve"]
        }
      }
    }
    ```
  - Updated `C:\Users\jib\.tokentracker\bin\notify.cjs` to execute `node.exe` directly via `process.execPath` to prevent fallback to `npx` or `uvx`.

---

### Incident 4: High-Precision Display Formatting
- **Requirement:** User requested high-precision visibility for percentages so small token usages are reflected immediately without rounding jumps.
- **Resolution:**
  - Changed formatting from `int(pct)` (e.g. `35%`) to 1 decimal place (`f"{pct:.1f}%"` e.g. `35.7% · 80.5%`).

---

## 3. Architecture & File Manifest

| File Path | Description |
| :--- | :--- |
| `taskbar_widget.py` | Native Win32 GDI Taskbar Embedded Text Widget (Single Source of Truth, GDI Font Caching, Hash Invalidation) |
| `auto_fetch.py` | Background quota fetcher & SSOT sync module (`fetch_all(silent=True)`) |
| `token_tracker.py` | Core data model & JSON state manager (`token_usage.json`) |
| `tray_widget.py` | Windows System Tray & Popup Dashboard application |
| `run_taskbar.bat` | Silent windowless launcher (`pythonw taskbar_widget.py`) |
| `run_widget.bat` | Silent windowless tray launcher (`pythonw tray_widget.py`) |
| `add_tokens.py` | CLI tool to manually log token usage |
| `problem.md` | **(This File)** Comprehensive retrospective & incident documentation for AI agents |

---

## 4. Operational Instructions for Future AI Agents

1. **Do NOT spawn external `python.exe` processes** for auto-fetching inside GUI event loops. Always use `threading.Thread(target=auto_fetch.fetch_all, kwargs={"silent": True}, daemon=True).start()`.
2. **Do NOT run CLI tools without `STARTUPINFO(wShowWindow=0)` and `0x08000008` (`CREATE_NO_WINDOW | DETACHED_PROCESS`)** on Windows 11.
3. **Do NOT use `"command": "uvx"` in `mcp_config.json`** on Windows 11. Point directly to the target `.exe` binary.
4. **Preserve Monotonic Quota Guard** (`min(incoming, current)`) within the same `reset_time` window to prevent quota bounce-back bugs.
