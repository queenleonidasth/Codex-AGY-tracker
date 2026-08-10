# Production AI Usage Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** เปลี่ยน Codex-AGY tracker เดิมให้เป็น Windows app ที่ติดตาม quota และ Codex token usage อัตโนมัติ มี state ที่ปลอดภัย UI ที่บอก freshness จริง และ build เป็น executable ได้

**Architecture:** Provider adapters คืน `ProviderSnapshot` รูปแบบเดียวให้ `UsageService` ซึ่งทำ TTL, single-flight, last-good fallback และ transactional persistence ผ่าน `AtomicStateStore` Taskbar, tray, dashboard และ CLI สร้าง view จาก state เดียวกัน โดยแยก source mode กับ packaged runtime paths

**Tech Stack:** Python 3.11+ (build ด้วย 3.13), stdlib `ctypes`/`tkinter`/`urllib`, pystray, Pillow, pytest, PyInstaller 6

## Global Constraints

- Target Windows 11 และ provider เฉพาะ Codex กับ Antigravity ในรอบนี้
- Local-only, no telemetry และห้าม log/copy access token, auth header, response body หรือ CSRF token
- ห้ามเปิด `agy.exe` เพื่อ refresh อัตโนมัติ; query ได้เฉพาะ process/local API ที่รันอยู่แล้ว
- Success TTL 60 วินาที, failure TTL 45 วินาที และ rate-limit TTL 5 นาที
- Last-good values ต้องถูก mark stale/error เมื่อ fetch ล้มเหลว ห้ามแสดงเป็น fresh หรือแทนด้วย 100%
- Packaged runtime data อยู่ที่ `%LOCALAPPDATA%\AIUsageTracker`; source mode migrate/ใช้ `data/` เดิม
- ทุก state mutation ต้องอยู่ใต้ thread lock + inter-process file lock และจบด้วย atomic replace
- UI ห้ามทำ Tk call จาก worker thread และ idle loop ห้าม reassert topmost ที่ 20 Hz
- ไม่เพิ่ม provider, cloud sync, browser-cookie extraction หรือ billing estimate ใน plan นี้

---

## File map

- Create `app_paths.py`: แยก source/resource/runtime paths และ frozen-process command
- Create `settings.py`: default config, deep merge และ validation
- Modify `quota_models.py`: normalized windows/snapshots, serialization และ structured errors
- Rewrite `state_store.py`: schema v3 migration, locking, atomic mutate และ corrupt recovery
- Create `codex_usage.py`: incremental active/archived JSONL aggregation
- Modify `codex_api_client.py`: structured live fetch result โดยไม่เผย secrets
- Modify `agy_api_client.py`: atomic cache write และ status-friendly failures
- Rewrite `quota_sources.py`: Codex/AGY adapters คืน normalized snapshot เท่านั้น
- Create `usage_service.py`: provider registry, TTL, single-flight, last-good และ refresh scheduler
- Rewrite `token_tracker.py`: read/mutate ผ่าน store และ expose summaries/view data
- Reduce `auto_fetch.py`: compatibility CLI ที่ delegate เข้า service
- Create `ui_models.py`: pure formatting/freshness/countdown model สำหรับทั้งสอง UI
- Create `dashboard.py`: Tk dashboard ที่อัปเดตผ่าน main thread
- Modify `tray_widget.py`: tray lifecycle/menu/notification ไม่มี dashboard Tk ใน worker
- Modify `taskbar_widget.py`: compact renderer, low-frequency positioning และ app orchestration
- Create `app.py`: entry point default/dashboard/refresh/diagnostics
- Create `diagnostics.py`: redacted health report และ rotating logging setup
- Create `startup.py`: HKCU startup registration ที่ชี้ไป absolute packaged/source command
- Create `setup.ps1`, `build.ps1`, `run.bat`, `AIUsageTracker.spec`, `requirements-dev.txt`
- Update `README.md`, `.gitignore`; retire compatibility launchers without breaking callers
- Add focused tests under `tests/`

### Task 1: Runtime paths, settings, and normalized domain model

**Files:**
- Create: `app_paths.py`
- Create: `settings.py`
- Modify: `quota_models.py`
- Test: `tests/test_settings_and_models.py`

**Interfaces:**
- Produces: `runtime_dir() -> Path`, `source_root() -> Path`, `build_child_command(mode: str) -> list[str]`
- Produces: `Settings.load(path: Path) -> Settings`, `Settings.to_dict() -> dict`
- Produces: `RateWindow`, `ProviderSnapshot`, `FetchStatus`, `ProviderErrorKind`, `ProviderFetchError`

- [ ] **Step 1: Write failing model/settings tests**

```python
def test_snapshot_round_trip_preserves_source_and_times():
    snap = ProviderSnapshot.ok("codex", "Codex", {"session": RateWindow("5H", 25, 300, "2026-08-10T12:00:00Z")}, source="live_api", observed_at="2026-08-10T10:00:00Z")
    assert ProviderSnapshot.from_dict(snap.to_dict()) == snap

def test_settings_clamps_refresh_and_thresholds(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"refresh_interval_seconds": 1, "notifications": {"thresholds": [20, 20, -1, 5]}}')
    settings = Settings.load(path)
    assert settings.refresh_interval_seconds == 30
    assert settings.notification_thresholds == (20, 5)
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings_and_models.py -q`

Expected: FAIL because `Settings`, `RateWindow` serialization and path helpers do not exist

- [ ] **Step 3: Implement immutable models and validated settings**

```python
class FetchStatus(str, Enum):
    OK = "ok"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"

@dataclass(frozen=True, slots=True)
class RateWindow:
    label: str
    used_percent: float
    window_minutes: int | None = None
    reset_at: str | None = None

    @property
    def remaining_percent(self) -> float:
        return round(100.0 - self.used_percent, 1)
```

`Settings.load` ต้อง deep-merge defaults, clamp refresh เป็น 30–3600 วินาที, normalize thresholds เป็น unique descending values 1–99 และเขียน default เมื่อไฟล์ยังไม่มี

- [ ] **Step 4: Run focused tests and full legacy tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings_and_models.py tests/test_quota_models.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add app_paths.py settings.py quota_models.py tests/test_settings_and_models.py tests/test_quota_models.py
git commit -m "refactor: define normalized tracker models and settings"
```

### Task 2: Transactional schema-v3 state store

**Files:**
- Rewrite: `state_store.py`
- Modify: `token_tracker.py`
- Test: `tests/test_state_store.py`

**Interfaces:**
- Consumes: `app_paths.runtime_dir()`
- Produces: `AtomicStateStore.load() -> dict`, `save(dict) -> None`, `mutate(Callable[[dict], None]) -> dict`
- Produces: `TokenTracker.add_usage(provider, input_tokens, output_tokens)` implemented only through `store.mutate`

- [ ] **Step 1: Write failing migration/concurrency/recovery tests**

```python
def test_mutate_preserves_two_concurrent_provider_updates(tmp_path):
    store_a = AtomicStateStore(tmp_path / "state.json")
    store_b = AtomicStateStore(tmp_path / "state.json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda p: (store_a if p == "codex" else store_b).mutate(lambda s: s["providers"].__setitem__(p, {"status": "ok"})), ["codex", "agy"]))
    assert set(store_a.load(force=True)["providers"]) == {"codex", "agy"}

def test_corrupt_file_is_backed_up_before_recovery(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken")
    AtomicStateStore(path).mutate(lambda state: state["usage"].update({"daily": {}}))
    assert list(tmp_path.glob("state.json.corrupt-*"))
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_state_store.py -q`

Expected: FAIL from missing schema v3/mutate and lost concurrent update

- [ ] **Step 3: Implement actual inter-process transaction**

```python
def mutate(self, change):
    with self._thread_lock, self._process_lock(timeout=5.0):
        state = self._read_fresh_or_recover()
        change(state)
        state["_meta"]["written_at"] = utc_now_iso()
        self._atomic_write(state)
        return copy.deepcopy(state)
```

`_process_lock` ต้อง open lock file แบบ `a+b`, lock byte 0 ด้วย `msvcrt.LK_NBLCK` และ retry ระยะสั้นจน timeout `_atomic_write` ต้อง `flush`, `os.fsync`, `os.replace` และ cleanup temp fileทุกทาง

- [ ] **Step 4: Migrate `TokenTracker` off direct JSON writes**

`TokenTracker` รับ `store`/`settings` ผ่าน constructor, summary methods โหลด fresh snapshot และ `add_usage` reject negative/non-integer counts ก่อน mutate daily/monthly/total ใน transaction เดียว

- [ ] **Step 5: Run store/tracker tests repeatedly**

Run: `1..20 | ForEach-Object { .venv\Scripts\python.exe -m pytest tests/test_state_store.py -q; if ($LASTEXITCODE) { exit $LASTEXITCODE } }`

Expected: 20 clean passes และ state JSON อ่านได้ทุกครั้ง

- [ ] **Step 6: Commit**

```powershell
git add state_store.py token_tracker.py tests/test_state_store.py
git commit -m "fix: make tracker state updates transactional"
```

### Task 3: Automatic Codex token aggregation

**Files:**
- Create: `codex_usage.py`
- Test: `tests/test_codex_usage.py`

**Interfaces:**
- Produces: `CodexUsageScanner(codex_homes: list[Path]).scan(previous_index: dict | None = None) -> ScanResult`
- `ScanResult` contains `daily`, `monthly`, `total`, `models`, `index`, `files_scanned`, `malformed_lines`

- [ ] **Step 1: Add fixture tests for delta and cumulative formats**

```python
def test_prefers_last_usage_and_falls_back_to_cumulative_delta(codex_home):
    write_rollout(codex_home, [token_event("2026-08-10T01:00:00Z", last={"input_tokens": 100, "output_tokens": 20}, total={"input_tokens": 100, "output_tokens": 20}), token_event("2026-08-10T02:00:00Z", total={"input_tokens": 180, "output_tokens": 50})])
    result = CodexUsageScanner([codex_home]).scan()
    assert result.daily["2026-08-10"]["input"] == 180
    assert result.daily["2026-08-10"]["output"] == 50

def test_active_copy_wins_over_same_archived_relative_path(codex_home):
    write_same_relative_rollouts(codex_home, active_total=120, archived_total=999)
    assert CodexUsageScanner([codex_home]).scan().total["total"] == 120
```

- [ ] **Step 2: Run test and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_codex_usage.py -q`

Expected: FAIL because scanner is absent

- [ ] **Step 3: Implement safe JSONL parser and active/archive dedupe**

Scanner ต้อง enumerate `sessions` ก่อน `archived_sessions`, key ด้วย `(home, relative_path)`, parse เฉพาะ `event_msg/token_count`, track model จาก `turn_context`, ใช้ non-negative numeric fields และข้าม malformed lines โดยนับ diagnostics

Delta rule:

```python
delta = info.get("last_token_usage")
if not valid_usage(delta):
    cumulative = normalized_usage(info.get("total_token_usage", {}))
    delta = subtract_non_negative(cumulative, prior_cumulative)
    prior_cumulative = cumulative
```

- [ ] **Step 4: Add changed-file index and replay fingerprint dedupe**

Persist per-file `{size, mtime_ns, aggregate}` และ reuse เมื่อ fingerprint เหมือนเดิม Global event fingerprint ใช้ timestamp/model/token tuple เพื่อไม่รวม history ที่ replay ข้าม subagent rollouts ซ้ำ ข้อมูลต่าง session ที่ไม่มี fingerprint ตรงกันยังนับแยก

- [ ] **Step 5: Run scanner tests including malformed/unchanged cases**

Run: `.venv\Scripts\python.exe -m pytest tests/test_codex_usage.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```powershell
git add codex_usage.py tests/test_codex_usage.py
git commit -m "feat: aggregate Codex token usage from local sessions"
```

### Task 4: Provider adapters and reliable usage service

**Files:**
- Modify: `codex_api_client.py`
- Modify: `agy_api_client.py`
- Rewrite: `quota_sources.py`
- Create: `usage_service.py`
- Rewrite: `auto_fetch.py`
- Test: `tests/test_provider_sources.py`
- Test: `tests/test_usage_service.py`

**Interfaces:**
- Consumes: normalized models, `AtomicStateStore`, `CodexUsageScanner`
- Produces: `CodexQuotaSource.fetch() -> ProviderSnapshot`, `AgyQuotaSource.fetch() -> ProviderSnapshot`
- Produces: `UsageService.refresh(provider_id: str | None = None, force: bool = False) -> dict[str, ProviderSnapshot]`
- Produces: `RefreshScheduler.start()`, `stop()`

- [ ] **Step 1: Write adapter contract tests**

```python
def test_codex_classifies_windows_by_duration_not_position():
    snapshot = CodexQuotaSource(fetch_live=lambda: wham_fixture(primary_seconds=604800, secondary_seconds=18000)).fetch()
    assert snapshot.windows["session"].window_minutes == 300
    assert snapshot.windows["weekly"].window_minutes == 10080

def test_agy_cache_is_stale_and_keeps_observed_timestamp(tmp_path):
    cache = write_agy_cache(tmp_path, age_seconds=600)
    snap = AgyQuotaSource(fetch_live=lambda: None, cache_path=cache, stale_seconds=300).fetch()
    assert snap.status is FetchStatus.STALE
    assert snap.source == "cache"
```

- [ ] **Step 2: Write service TTL/single-flight/last-good tests**

```python
def test_failure_reuses_windows_but_marks_error(store, clock):
    provider = SequenceProvider([ok_snapshot(40), ProviderFetchError(ProviderErrorKind.TIMEOUT, "timed out")])
    service = UsageService(store, {"codex": provider}, clock=clock)
    service.refresh(force=True)
    failed = service.refresh(force=True)["codex"]
    assert failed.windows["session"].remaining_percent == 60
    assert failed.status is FetchStatus.ERROR
    assert failed.message == "timed out"
```

- [ ] **Step 3: Run focused tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_provider_sources.py tests/test_usage_service.py -q`

Expected: FAIL because adapters still return legacy dicts and service is absent

- [ ] **Step 4: Implement provider error mapping and normalized adapters**

Codex maps 401/403 -> `AUTH_REQUIRED`, 429 -> `RATE_LIMITED`, timeout -> `TIMEOUT`, malformed -> `PARSE`; JSONL fallback source is `session_log` AGY maps process-not-running -> cache or `UNAVAILABLE` และ cache age -> `STALE` Cache writes use temp+replace

- [ ] **Step 5: Implement service cache policy and state mutation**

```python
TTL = {FetchStatus.OK: 60, FetchStatus.STALE: 45, FetchStatus.RATE_LIMITED: 300, FetchStatus.ERROR: 45, FetchStatus.UNAVAILABLE: 45}
```

Store provider snapshot และ scanner totals ใน `store.mutate` เดียวต่อ refresh result; last-good fallback copy เฉพาะ windows/observed_at/source เดิม และคง status/message ล่าสุด

- [ ] **Step 6: Convert `auto_fetch.py` to compatibility wrapper**

`fetch_all(silent=False, force=False)` สร้าง/ใช้ singleton service, คืน snapshots และไม่มี legacy load/save sequence ส่วน `--daemon` ใช้ scheduler interval จาก settings ไม่ hard-code 5 วินาที

- [ ] **Step 7: Run tests and network-free integration test**

Run: `.venv\Scripts\python.exe -m pytest tests/test_provider_sources.py tests/test_usage_service.py tests/test_codex_usage.py tests/test_state_store.py -q`

Expected: PASS without reading real credentials or network

- [ ] **Step 8: Commit**

```powershell
git add codex_api_client.py agy_api_client.py quota_sources.py usage_service.py auto_fetch.py tests/test_provider_sources.py tests/test_usage_service.py
git commit -m "feat: add reliable provider refresh service"
```

### Task 5: Shared UI model, dashboard, tray, and taskbar

**Files:**
- Create: `ui_models.py`
- Create: `dashboard.py`
- Rewrite: `tray_widget.py`
- Modify: `taskbar_widget.py`
- Create: `app.py`
- Test: `tests/test_ui_models.py`

**Interfaces:**
- Produces: `build_provider_view(snapshot: dict, now: datetime) -> ProviderView`
- Produces: `format_countdown(reset_at, now) -> str`, `compact_segments(state) -> list[TextSegment]`
- `app.main(argv=None) -> int` supports default, `--dashboard`, `--refresh`, `--diagnostics`

- [ ] **Step 1: Write pure UI-model tests**

```python
def test_stale_compact_text_never_defaults_missing_quota_to_100():
    view = build_provider_view({"display_name": "Codex", "status": "stale", "windows": {}}, NOW)
    assert view.compact_text == "Codex ~ —"

def test_countdown_uses_hours_then_minutes():
    assert format_countdown("2026-08-10T12:30:00Z", parse("2026-08-10T10:00:00Z")) == "2h 30m"
```

- [ ] **Step 2: Run UI-model tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui_models.py -q`

Expected: FAIL because UI model is absent

- [ ] **Step 3: Implement shared formatting model**

Build labels from actual window labels, one decimal percent, reset countdown, source and age `~` for stale, `!` for error/unavailable/rate-limited สี warning เมื่อ remaining <= 20 และ critical เมื่อ <= 10

- [ ] **Step 4: Build dashboard on Tk main thread**

`Dashboard.run()` owns `Tk.mainloop`; refresh starts worker, worker queues result, and `root.after(100, drain_queue)` alone mutates widgets Cards show quota bars, plan/source/last-confirmed/error, today/month/all Codex token totals and buttons Refresh/Diagnostics/Close

- [ ] **Step 5: Integrate tray and taskbar lifecycle**

Default `app.py` starts scheduler, `pystray.Icon.run_detached()`, then Win32 taskbar message loop Context actions launch same executable/source command with `--dashboard`; Refresh calls service in worker; Exit stops scheduler/icon and posts `WM_CLOSE`

Taskbar changes:

- repaint only when serialized `compact_segments` changes
- timer interval 1 วินาทีสำหรับ countdown/reposition แต่ provider refresh อยู่ scheduler 60 วินาที
- remove `keep_top` 20 Hz thread
- handle `WM_DISPLAYCHANGE`, `WM_SETTINGCHANGE`, `WM_DPICHANGED` by recalculating taskbar rectangle
- paint stale/error suffix and do not access state during GDI drawing

- [ ] **Step 6: Run model tests and import smoke test**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui_models.py -q; .venv\Scripts\python.exe -c "import app, dashboard, tray_widget, taskbar_widget"`

Expected: PASS with no window opened during import

- [ ] **Step 7: Commit**

```powershell
git add ui_models.py dashboard.py tray_widget.py taskbar_widget.py app.py tests/test_ui_models.py
git commit -m "feat: deliver unified taskbar tray and dashboard UI"
```

### Task 6: Diagnostics, notifications, setup, and packaged build

**Files:**
- Create: `diagnostics.py`
- Create: `startup.py`
- Create: `setup.ps1`
- Create: `build.ps1`
- Create: `run.bat`
- Create: `AIUsageTracker.spec`
- Create: `requirements-dev.txt`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Modify: `run_taskbar.bat`
- Modify: `run_widget.bat`
- Modify: `usage_service.py`
- Modify: `tray_widget.py`
- Modify: `app.py`
- Test: `tests/test_diagnostics.py`
- Test: `tests/test_notifications.py`
- Test: `tests/test_startup.py`

**Interfaces:**
- Produces: `collect_diagnostics(settings, state) -> dict` and `render_diagnostics(report) -> str`
- Produces: `NotificationPolicy.events(previous_state, snapshots) -> list[NotificationEvent]`
- Produces: `set_startup(enabled: bool, command: list[str]) -> None`, `is_startup_enabled() -> bool`

- [ ] **Step 1: Write redaction and notification-dedupe tests**

```python
def test_diagnostics_never_emits_auth_values(tmp_path):
    report = render_diagnostics(collect_diagnostics_for_test(auth_token="secret-value"))
    assert "secret-value" not in report
    assert "access_token" not in report.lower()

def test_threshold_fires_once_per_reset_window():
    first = policy.events({}, {"codex": snapshot(remaining=19, reset="A")})
    second = policy.events(policy.apply({}, first), {"codex": snapshot(remaining=18, reset="A")})
    assert len(first) == 1 and second == []
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_diagnostics.py tests/test_notifications.py -q`

Expected: FAIL because modules are absent

- [ ] **Step 3: Implement rotating logs, health report, and notification state**

Use `RotatingFileHandler(maxBytes=1_000_000, backupCount=3)` Diagnostics reports only booleans, versions, sanitized paths, timestamps, status/source and error kind Notification key is `provider/window/reset_at/threshold`

เพิ่ม startup registration ที่ `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` ชื่อ `AIUsageTracker`; quote argument ด้วย `subprocess.list2cmdline`, ไม่ขอ admin และลบเฉพาะ value ชื่อนี้เมื่อ disable Service บันทึก notification keys ใน state transaction และ tray ส่ง `icon.notify` เฉพาะ event ใหม่ Dashboard toggle เรียก `set_startup` ผ่าน Tk main thread

- [ ] **Step 4: Implement reproducible environment/setup scripts**

`setup.ps1` checks `py -3.13`, known per-user Python path, then `winget install --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements`; creates `.venv`, installs `requirements.txt` and `requirements-dev.txt`, runs tests

`run.bat` order:

```bat
if exist "%~dp0dist\AIUsageTracker\AIUsageTracker.exe" start "" "%~dp0dist\AIUsageTracker\AIUsageTracker.exe" %*
if exist "%~dp0dist\AIUsageTracker\AIUsageTracker.exe" exit /b 0
if exist "%~dp0.venv\Scripts\pythonw.exe" start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" %*
if exist "%~dp0.venv\Scripts\pythonw.exe" exit /b 0
echo AIUsageTracker is not set up. Run setup.ps1 first.
exit /b 1
```

- [ ] **Step 5: Add PyInstaller onedir/windowed spec and build gate**

`build.ps1` runs full pytest, clears only resolved project `build/` and `dist/AIUsageTracker/`, then `.venv\Scripts\pyinstaller.exe --noconfirm AIUsageTracker.spec`; spec entry is `app.py`, name `AIUsageTracker`, `console=False`, includes Pillow/pystray hooks and no runtime data files

- [ ] **Step 6: Run packaging tests and build executable**

Run: `powershell -ExecutionPolicy Bypass -File .\build.ps1`

Expected: full tests PASS and `dist\AIUsageTracker\AIUsageTracker.exe` exists

- [ ] **Step 7: Commit**

```powershell
git add diagnostics.py startup.py setup.ps1 build.ps1 run.bat AIUsageTracker.spec requirements.txt requirements-dev.txt .gitignore run_taskbar.bat run_widget.bat usage_service.py tray_widget.py app.py tests/test_diagnostics.py tests/test_notifications.py tests/test_startup.py
git commit -m "build: package tracker as a windowless Windows app"
```

### Task 7: Documentation and end-to-end verification

**Files:**
- Rewrite: `README.md`
- Modify: `problem.md`
- Create: `tests/test_integration_refresh.py`

**Interfaces:**
- Consumes all public interfaces from Tasks 1–6
- Produces operator documentation and final acceptance evidence

- [ ] **Step 1: Add offline integration test**

```python
def test_refresh_persists_quota_and_automatic_tokens(tmp_path, codex_home):
    store = AtomicStateStore(tmp_path / "state.json")
    service = fixture_service(store, codex_home, codex_snapshot=ok_snapshot(used=25))
    service.refresh(force=True)
    state = store.load(force=True)
    assert state["providers"]["codex"]["windows"]["session"]["used_percent"] == 25
    assert state["usage"]["daily"]["2026-08-10"]["codex"]["total"] > 0
```

- [ ] **Step 2: Run full automated verification**

Run: `.venv\Scripts\python.exe -m pytest -q; .venv\Scripts\python.exe -m compileall -q .`

Expected: PASS and exit code 0

- [ ] **Step 3: Rewrite operator documentation**

README must include one-command setup, run/build, screen/status legend, source priority, privacy, data/log paths, startup command, diagnostics, troubleshooting for missing Codex auth/AGY not running and exact test command Update `problem.md` status to point to this implementation and remove claims no longer true

- [ ] **Step 4: Perform Windows live smoke checks**

Run packaged `AIUsageTracker.exe --refresh`, `--diagnostics` and `--dashboard`; launch default twice and verify one widget instance; observe process creation across at least two scheduler intervals and confirm no tracker-created `cmd.exe`, `conhost.exe` or `agy.exe`

- [ ] **Step 5: Inspect saved state and logs without exposing secrets**

Confirm schema version 3, provider source/status/observed times, Codex token totals and valid JSON Confirm log rotation path and scan tracked/untracked files for token-like secrets using key-name patterns only

- [ ] **Step 6: Final diff/test review and commit**

```powershell
git diff --check
git status --short
git add README.md problem.md tests/test_integration_refresh.py
git commit -m "docs: document production tracker operation"
git log --oneline --decorate -10
```

Expected: clean worktree, all acceptance checks recorded in final handoff
