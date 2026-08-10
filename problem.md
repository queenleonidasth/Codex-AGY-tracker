# AI Token Tracker Widget v2 — Technical Retrospective & Problem Incident Report

> [!WARNING] เอกสารนี้เป็น retrospective จาก implementation เดิมและข้อความ "Fully Resolved" ด้านล่างไม่ตรงกับผลตรวจระบบวันที่ 2026-08-01 แล้ว โปรดใช้ `docs/superpowers/specs/2026-08-01-quota-tracker-reliability-design.md` เป็น source of truth สำหรับ root cause, architecture และ acceptance criteria ปัจจุบัน

> **Target Audience:** Future AI Agents & Systems Developers**Date:** August 1, 2026**System Location:** `C:\Users\jib\.quickwork\profiles\enterprise-2076315bcdb6\sessions\a0419935-6f63-4f7c-96b9-05ccabe83aac\workspace\artifacts\ai_token_widget_v2\`**Status:** Fully Resolved & Verified (100% Silent Background Execution, High-Precision Quota Syncing, Monotonic Quota Guard)

---

## 1. System Overview

The **AI Token Usage Taskbar Embedded Widget v2** is a native Win32 application written in Python (`ctypes`, Win32 GDI API) that renders real-time token consumption and live rate limit quotas directly onto the Windows 11 Taskbar.

### Primary Providers Tracked:

- **AGY CLI (**`agy.exe`**)**: Google AI Pro Plan (Gemini 3.6 Flash - 5-Hour & Weekly quota limits).
- **Codex CLI**: OpenAI GPT-5.5 / GPT-5.5-preview rollout session limits.
- **DeepSeek & Mimo**: Secondary AI providers.

---

## 2. Comprehensive Incident & Resolution Log

### Incident 1: Stale AGY Quota & Quota Bounce-Back Bug

- **Symptom:** Reading `agy_quota_cache.json` passively left data outdated. When updated, numbers would temporarily drop (e.g. from `43.7%` to `35.7%`) but then bounce back up to `43.7%`.
- **Root Cause:**1. `agy.exe -p /usage` outputs JSON in two passes: pass 1 (local cached session snapshot) and pass 2 (live Google server response). Pass 1 was overwriting live server data.

1. Subprocess calls without active background triggers meant `agy_quota_cache.json` was only updated when the user manually ran AGY commands.

- **Resolution:**- Implemented **Active Background Refresh** (`trigger_agy_background_refresh`) inside `auto_fetch.py`.
- Implemented **Monotonic Quota Guard** in both `agy_statusline.py` and `auto_fetch.py`:```python

# Within the same reset window (reset_time), remaining quota fraction can ONLY decrease

if old_group and old_group.get("reset_time") == reset_time: final_frac = min(incoming_frac, old_frac)

```

---

### Incident 2: Black CMD Console Window Flashing

- **Symptom:** Small black CMD console windows flashed on the user's screen every 3 to 12 seconds when the widget refreshed quota data.
- **Root Cause:**1. Spawning `python.exe` subprocesses from `taskbar_widget.py` via `subprocess.Popen([sys.executable, "auto_fetch.py"])` created a new Windows Console Host (`conhost.exe`) instance every refresh cycle.
2. Spawning `agy.exe` without Win32 `STARTUPINFO` flags caused console window flashes.
- **Resolution:**- **In-Process Thread Execution:** Replaced external `python.exe` subprocess creation in `taskbar_widget.py` with in-process daemon threads:```python
threading.Thread(target=auto_fetch.fetch_all, kwargs={"silent": True}, daemon=True).start()

```

- **Win32 Dual-Flag Subprocess Detachment:** Updated `trigger_agy_background_refresh()` in `auto_fetch.py` with:```python si = subprocess.STARTUPINFO() si.dwFlags |= subprocess.STARTF_USESHOWWINDOW si.wShowWindow = 0 # SW_HIDE creationflags = 0x08000008 # CREATE_NO_WINDOW (0x08000000) | DETACHED_PROCESS (0x00000008)

```
- **Windowless Launcher:** Updated `run_taskbar.bat` and `run_widget.bat` to launch via `pythonw.exe`:```bat
@echo off
start "" pythonw "%~dp0taskbar_widget.py"

```

---

### Incident 3: Spurious `uvx.exe` Console Tab Popups (PARTIALLY RESOLVED)

- **Symptom:** Windows Terminal repeatedly opened new tabs titled `C:\Users\jib\AppData\Local\hermes\hermes-agent\venv\Scripts\uvx.exe`.
- **Root Cause:**- AI Assistant MCP configuration at `C:\Users\jib\.gemini\config\mcp_config.json` had `"command": "uvx"` configured for `windows-mcp`.
- Every time the AI agent initialized or invoked MCP tools, the MCP client executed `uvx.exe`, causing Windows Terminal on Windows 11 to open a console tab.
- **Resolution:**- Updated `C:\Users\jib\.gemini\config\mcp_config.json` to point directly to the native executable binary:```json { "mcpServers": { "windows-mcp": { "command": "C:\Users\jib\AppData\Roaming\uv\tools\windows-mcp\Scripts\windows-mcp.exe", "args": ["serve"] } } }

```
- Updated `C:\Users\jib\.tokentracker\bin\notify.cjs` to execute `node.exe` directly via `process.execPath` to prevent fallback to `npx` or `uvx`.

---

### Incident 4: High-Precision Display Formatting

- **Requirement:** User requested high-precision visibility for percentages so small token usages are reflected immediately without rounding jumps.
- **Resolution:**- Changed formatting from `int(pct)` (e.g. `35%`) to 1 decimal place (`f"{pct:.1f}%"` e.g. `35.7% · 80.5%`).

---

### Incident 5: CMD Window `windows-mcp.exe` โผล่ซ้ำทุก ~15 วินาที (CONFIRMED — 2026-08-01)

- **Symptom:** หน้าต่าง CMD ที่มี title `C:\Users\jib\AppData\Roaming\uv\tools\windows-mcp\Scripts\windows-mcp.exe` โผล่ขึ้นมาทุก ~15 วินาที **แม้ปิด terminal ทั้งหมดแล้ว** (widget ยังรันเป็น pythonw.exe ที่มองไม่เห็น)

- **Root Cause (ยืนยันจาก log evidence แล้ว):**

```

taskbar_widget.py (pythonw.exe — invisible, ไม่ตายเมื่อปิด terminal) ↓ timer ทุก 3 วินาที, ทุก 5 ticks (15 วินาที) เรียก: auto_fetch.fetch_all(silent=True) ↓ ถ้า agy_quota_cache.json เก่ากว่า 15 วินาที: trigger_agy_background_refresh() ↓ subprocess.Popen(['agy.exe', '-p', '/usage'], creationflags=DETACHED_PROCESS) ↓ AGY starts full language server + MCP manager mcp_manager.go อ่าน C:\Users\jib.gemini\config\mcp_config.json ↓ พบ "windows-mcp" entry spawn('C:...\windows-mcp.exe', ['serve']) ↓ windows-mcp.exe เป็น CONSOLE APP — ไม่ถูก hide 💥 CMD WINDOW APPEARS! ↓ ~2.5 วินาทีต่อมา AGY session จบ mcp_manager kills windows-mcp.exe (exit 0xc000013a) ↓ 15 วินาทีต่อมา วนซ้ำ

```

- **ทำไมปิด terminal แล้วยังมี:**
- `taskbar_widget.py` ถูกเปิดด้วย `pythonw.exe` (windowless) ผ่าน `run_taskbar.bat`
- มันรันเป็น background process ไม่ขึ้นกับ terminal ใดๆ
- ต้อง kill `pythonw.exe` ผ่าน Task Manager จึงจะหยุด

- **Log Evidence:**
- AGY log files สร้างทุก ~15 วินาที (ตรงกับ widget timer):

```

cli-20260801_173716.log → cli-20260801_173731.log → cli-20260801_173746.log (ห่าง 15s) cli-20260801_144411.log → cli-20260801_144423.log → cli-20260801_144435.log (ห่าง 12s)

```
- ทุก log มี: `mcp_manager.go:1458] Failed to close MCP instance "windows-mcp": exit status 0xc000013a`

- **Key Config Files:**

```

C:\Users\jib.gemini\config\mcp_config.json: {"mcpServers": {"windows-mcp": { "command": "C:\Users\jib\AppData\Roaming\uv\tools\windows-mcp\Scripts\windows-mcp.exe", "args": ["serve"] }}}

C:\Users\jib.gemini\antigravity-cli\settings.json: {"statusLine": {"command": "python C:/Users/jib/.tokentracker/tracker/agy_statusline.py"}}

```

- **Process Tree:**

```

pythonw.exe (taskbar_widget.py — ไม่มีหน้าต่าง, อยู่ใน Task Manager) └─ Thread: auto_fetch.fetch_all() └─ trigger_agy_background_refresh() └─ agy.exe -p /usage (DETACHED_PROCESS, หมดใน ~2.5s) ├─ language server (pid xxxx) ├─ mcp_manager → windows-mcp.exe serve ← 💥 CMD POPUP └─ statusline → python agy_statusline.py → เขียน cache

```

- **วิธีแก้ที่แนะนำ (เรียงตามแนะนำ):**

| # | แนวทาง | ผล | ข้อเสีย |
|---|---------|-----|---------|
| 1 | **ลบ `windows-mcp` ออกจาก `mcp_config.json`** | หยุด popup ทันที | AGY ใช้ Windows automation ไม่ได้ (Screenshot, Click, PowerShell tools) |
| 2 | **ให้ `auto_fetch.py` อ่านเฉพาะ cache โดยไม่ trigger AGY refresh** | ไม่ spawn agy.exe ซ้ำ | quota data อาจ stale ถ้าไม่มี AGY session อื่นรัน |
| 3 | **ลดความถี่ refresh จาก 15s เป็น 5 นาที** | ลดจำนวน popup ลงมาก | ยังมีอยู่ แค่น้อยลง |
| 4 | **สร้าง wrapper ที่ launch windows-mcp.exe ด้วย CREATE_NO_WINDOW** | ซ่อน console | ต้องสร้าง .exe wrapper + อาจเสีย stdio pipe |

- **Status:** ✅ RESOLVED — ใช้แนวทาง #2: ลบ `trigger_agy_background_refresh()` ออกจาก `fetch_agy_quota_cache()` แล้ว (cache ยังอัปเดตผ่าน `agy_statusline.py` hook เมื่อ user ใช้ AGY จริง, manual refresh ผ่าน `python auto_fetch.py --refresh-agy`)

---

## 3. Architecture & File Manifest

| File Path | Description |
| --- | --- |
| `taskbar_widget.py` | Native Win32 GDI Taskbar Embedded Text Widget (Single Source of Truth, GDI Font Caching, Hash Invalidation) |
| `auto_fetch.py` | Background quota fetcher & SSOT sync module (`fetch_all(silent=True)`) |
| `token_tracker.py` | Core data model & JSON state manager (`token_usage.json`) |
| `tray_widget.py` | Windows System Tray & Popup Dashboard application |
| `quota_models.py` | Dataclasses/enums for quota windows, provider snapshots, monotonic guard |
| `quota_sources.py` | Provider adapters (CodexQuotaSource, AgyQuotaSource) |
| `refresh_service.py` | RefreshCoordinator (single-flight, backoff, DETACHED_PROCESS constant) |
| `state_store.py` | AtomicStateStore (atomic write, inter-process lock, freshness metadata) |
| `run_taskbar.bat` | Silent windowless launcher with single-instance guard |
| `run_widget.bat` | Silent windowless tray launcher (`pythonw tray_widget.py`) |
| `add_tokens.py` | CLI tool to manually log token usage |
| `tests/test_quota_models.py` | Unit tests for all reliability fixes |
| `.gitignore` | Excludes **pycache**, runtime data, logs from Git |
| `problem.md` | **(This File)** Comprehensive retrospective & incident documentation for AI agents |

---

## 4. Operational Instructions for Future AI Agents

1. **Do NOT spawn external **`python.exe`** processes** for auto-fetching inside GUI event loops. Always use `threading.Thread(target=auto_fetch.fetch_all, kwargs={"silent": True}, daemon=True).start()`.
2. **Do NOT use magic number **`0x08000008` — use named constant `DETACHED_PROCESS = 0x00000008` with `STARTUPINFO(wShowWindow=0)` separately. The combined flag is contradictory per Microsoft docs.
3. **Do NOT use **`"command": "uvx"`** in **`mcp_config.json` on Windows 11. Point directly to the target `.exe` binary.
4. **Preserve Monotonic Quota Guard** — use `apply_monotonic_guard()` from `quota_models.py` which guards per-window (5h and weekly independently).
5. **Be aware that **`agy.exe`** spawns MCP servers** listed in `~/.gemini/config/mcp_config.json` every time it starts a session. Any tool that triggers `agy.exe` (including background refresh) will cause windows-mcp.exe CMD popups.
6. **Use AtomicStateStore** for all state persistence — never write directly to `data/token_usage.json` without lock.
7. **Do NOT commit runtime state to Git** — `data/token_usage.json`, `data/config.json`, and `__pycache__/` are excluded by `.gitignore`.

```

