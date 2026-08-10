# Production AI Usage Tracker Design

> วันที่: 2026-08-10
>
> สถานะ: อนุมัติตามสิทธิ์ตัดสินใจที่ผู้ใช้มอบไว้ในคำขอ
>
> เป้าหมายระบบ: Windows 11, Codex และ Antigravity (AGY), local-first

## 1. สรุป

ปรับโปรเจ็กต์ Python/Win32 เดิมให้เป็นแอปติดตาม AI usage ที่ใช้ประจำวันได้จริง โดยไม่ rewrite เป็นเทคโนโลยีใหม่ทั้งชุด แอปต้องแสดงทั้ง quota คงเหลือและ token usage ที่ตรวจได้จากข้อมูลในเครื่อง พร้อมบอกอย่างตรงไปตรงมาว่าข้อมูลมาจากไหน สดแค่ไหน และล้มเหลวเพราะอะไร

สถาปัตยกรรมใหม่แยก provider, การ normalize ข้อมูล, persistence, background refresh และ UI ออกจากกัน ทุก UI อ่าน state เดียวกัน การเขียน state ต้อง atomic และไม่ทำ lost update เมื่อ taskbar, dashboard หรือ CLI ทำงานพร้อมกัน

## 2. หลักฐานจากระบบเดิม

ปัญหาที่ต้องแก้ก่อนเรียกว่า production-ready:

- `token_tracker.py` เขียน JSON โดยตรง ข้าม `AtomicStateStore` และทำให้เกิด partial/lost update ได้
- `AtomicStateStore` ประกาศ file-lock helper แต่ไม่ได้ใช้จริงใน read-modify-write
- `auto_fetch.fetch_all()` เขียน provider ทีละครั้ง แล้วเขียน state เก่าทับ metadata อีกรอบ
- refresh coordinator ถือว่าผล `None` สำเร็จ จึงไม่ backoff เมื่อ provider ใช้งานไม่ได้
- taskbar poll ทุก 3 วินาทีแต่ยิง network/live probe ทุก 15 วินาที และมี topmost loop 20 ครั้งต่อวินาที
- UI เตรียมสี stale ไว้แต่ไม่ได้วาด stale/error indicator
- dashboard แสดง budget ที่กำหนดเองแทน quota จริง และ Tk ทำงานใน worker thread
- `os.startfile()` กับไฟล์ `.py` และ launcher ที่อาศัย `pythonw` ใน PATH ใช้ไม่ได้ในเครื่องปัจจุบัน
- Codex token totals ต้องเพิ่มด้วยมือ ทั้งที่ rollout JSONL มีข้อมูลสะสมอัตโนมัติ
- ไม่มี packaging, health diagnostics, rotating logs, config validation หรือ end-to-end smoke test

## 3. แนวทางที่พิจารณา

### A. ปะแก้เฉพาะไฟล์เดิม

เร็วที่สุดและ diff เล็ก แต่ยังคง legacy dict หลายรูปแบบ การเขียน state หลายทาง และ UI ที่ผูกกับ I/O แน่นเกินไป ความเสี่ยง regression สูงเมื่อเพิ่ม provider

### B. Modular Python refactor โดยคง Win32 widget (เลือก)

สร้าง model และ service กลาง ใช้ provider adapters, transactional store และ renderer/view-model ที่ทดสอบได้ คง Python, Tk และ Win32 ที่มีอยู่เพื่อให้ส่งมอบได้เร็ว เพิ่ม PyInstaller build ให้ผู้ใช้ไม่ต้องติดตั้ง Python หลัง build

### C. Rewrite ด้วย WinUI 3/.NET

เหมาะที่สุดสำหรับ multi-monitor, DPI และ taskbar integration ระยะยาว แต่ต้องติดตั้ง toolchain ใหม่และเขียน UI/process detection ใหม่เกือบทั้งหมด ไม่คุ้มกับขอบเขต Codex + AGY รอบนี้

## 4. ขอบเขต

### ต้องมี

- Codex quota: live API เมื่อ credentials ใช้ได้ และ session JSONL เป็น fallback
- Antigravity quota: localhost language-server API เมื่อรันอยู่ และ last-good cache เป็น fallback
- Codex token usage: วันนี้ เดือนนี้ และทั้งหมด จาก active/archived rollout JSONL
- state ของ provider แบบ normalized: windows, status, source, fetched/confirmed time, plan และ error
- success TTL 60 วินาที, failure TTL 45 วินาที, rate-limit TTL 5 นาที และ single-flight ต่อ provider
- last-good snapshot อยู่ต่อเมื่อ fetch ล้มเหลว แต่ต้องถูก mark stale/error ห้ามทำเป็น fresh
- taskbar compact view, tray/dashboard, manual refresh, diagnostics และ exit
- notification เมื่อ quota ผ่าน threshold ต่ำ โดย throttle ต่อ provider/window/reset period
- config validation พร้อม default ที่ปลอดภัย
- local-only, no telemetry, ไม่ copy หรือ log access token
- one-command setup และ build เป็น Windows executable แบบ windowless

### ยังไม่ทำ

- รองรับ provider นอก Codex/Antigravity
- team/cloud sync, remote dashboard หรือ analytics backend
- billing ที่อ้างว่าแม่นยำ หากไม่มี price metadata ที่ตรวจสอบได้
- browser cookie extraction หรือเก็บ credentials ใหม่
- taskbar injection แบบ WinUI/XAML island และ multi-monitor ขั้นสูง
- reverse-engineer API ที่ต้องเปิด AGY process ใหม่หรือหลบ security control

## 5. Architecture

```text
Codex API / rollout JSONL     AGY localhost / cache
            |                           |
            +---- provider adapters ----+
                         |
                 ProviderSnapshot
                         |
              UsageService + TTL/backoff
                         |
               AtomicStateStore v3
                  /        |       \
           taskbar UI   dashboard   CLI/diagnostics
```

### 5.1 Domain model

`ProviderSnapshot` เป็นข้อมูลหลักหนึ่งรูปแบบ:

- `provider_id`, `display_name`, `status`
- `windows`: map ของ window id ไปยัง label, used/remaining percent, duration และ reset time
- `source`: `live_api`, `local_api`, `session_log` หรือ `cache`
- `observed_at`: เวลาที่ source ยืนยันค่าจริง
- `refreshed_at`: เวลาที่แอปพยายาม refresh ล่าสุด
- `plan`, `message`

Status ใช้ `ok`, `stale`, `unavailable`, `error`, `rate_limited` และต้องไม่อนุมานว่าไม่มีข้อมูลเท่ากับเหลือ 100%

### 5.2 Provider adapters

แต่ละ adapter มี `fetch() -> ProviderSnapshot` และไม่มี UI/persistence:

- Codex live adapter อ่าน auth ที่มีอยู่แบบ read-only, timeout สั้น, normalize window ตาม duration ไม่ตามตำแหน่ง
- Codex log adapter เลือก rate-limit event ใหม่สุดด้วย parsed timestamp และสแกน token_count จากทั้ง `sessions` กับ `archived_sessions`
- token scanner ใช้ `last_token_usage` เป็น delta ก่อน ถ้าไม่มีจึงลบ cumulative total ก่อนหน้าใน session เดียวกัน และให้ active file ชนะ archived file ที่ relative path ซ้ำ
- AGY adapter query process ที่รันอยู่ผ่าน localhost เท่านั้น; ถ้าทำไม่ได้จึงคืน persisted cache พร้อม stale age

### 5.3 Usage service

Service เป็นเจ้าของ provider registry, in-memory cache และ single-flight:

- success ใช้ TTL 60 วินาที
- auth/not-running/parse failure ใช้ TTL 45 วินาที
- HTTP 429 ใช้ TTL 5 นาที
- force refresh ล้าง TTL แต่ยังไม่เปิดให้ซ้อน fetch
- exception ถูกแปลงเป็น status ที่คง last-good windows และ observed timestamp เดิม
- refresh loop ปกติทุก 60 วินาที ไม่มี subprocess/console flash

### 5.4 Persistence

State schema v3 แยก `providers`, `usage`, `notifications` และ `_meta` การเปลี่ยนข้อมูลทุกครั้งทำใน `store.mutate(callback)` ภายใต้ thread lock + inter-process file lock แล้วเขียน temp file, flush, `fsync`, `os.replace`

Migration ต้องรับ schema v1/v2 เดิมโดยไม่ทิ้ง daily/monthly/total หรือ rate limits ที่มีอยู่ การโหลด JSON เสียหายต้องเก็บไฟล์สำรองชื่อ `.corrupt-<timestamp>` แล้วเริ่ม state ว่าง พร้อม log warning

Runtime data อยู่ใน `%LOCALAPPDATA%\AIUsageTracker` เมื่อ packaged และใช้โฟลเดอร์ `data/` เดิมในโหมด source เพื่อ migration ที่ไม่ทำข้อมูลเดิมหาย

### 5.5 UI

Taskbar view แสดง `Provider 5H% · W%` พร้อมสีตามระดับและสัญลักษณ์:

- ไม่มีสัญลักษณ์: fresh
- `~`: stale/last-good
- `!`: error/unavailable

Tooltip/context menu แสดง source, last confirmed, reset countdown และ error แบบอ่านได้ การ repaint เกิดเมื่อ view-model เปลี่ยนเท่านั้น Topmost ถูก reassert ด้วย timer ความถี่ต่ำและ reposition เมื่อ display/taskbar setting เปลี่ยน

Dashboard แสดง card ของแต่ละ provider พร้อม progress bars ของทุก window, reset countdown, plan/source/freshness, token totals และปุ่ม Refresh/Diagnostics/Startup setting โดย UI update ผ่าน Tk main thread เท่านั้น

## 6. Error handling และ observability

- rotating log ขนาดจำกัดใน `%LOCALAPPDATA%\AIUsageTracker\logs`
- ไม่ log auth header, token, response body หรือ command line ที่อาจมี CSRF token
- diagnostics แสดง path/source availability และข้อความแก้ไข เช่น “เปิด Codex หนึ่งครั้งเพื่อ refresh sign-in”
- background exception ทุกตัวถูก log; UI loop ต้องไม่หยุด
- network/local API ใช้ timeout และคืน structured failure
- notification ยิงครั้งเดียวต่อ threshold และ reset identity

## 7. Packaging และ operation

- `setup.ps1` หา Python ที่ใช้ได้ หรือ install Python แบบ user-scope ผ่าน winget แล้วสร้าง `.venv`
- `build.ps1` รัน tests ก่อน build และสร้าง `dist/AIUsageTracker/AIUsageTracker.exe` แบบ onedir/windowed เพื่อ startup เร็วและวิเคราะห์ปัญหาง่ายกว่า onefile
- `run.bat` เลือก packaged executable ก่อน แล้ว fallback ไป `.venv\Scripts\pythonw.exe`
- startup registration เป็น explicit command/setting และชี้ไป executable/launcher แบบ absolute path
- source mode และ packaged mode ใช้ resource/runtime path คนละหน้าที่ ไม่เขียนข้อมูลลง PyInstaller extraction directory

## 8. Test strategy

### Unit

- percent/window normalization และ timestamp parsing
- Codex last-token delta, cumulative fallback, archived dedupe และ malformed JSONL
- AGY group classification สำหรับ 5h/weekly และหลายกลุ่ม
- TTL แยก success/failure/rate-limit, single-flight และ last-good stale behavior
- schema migration, concurrent mutate, metadata preservation และ corrupt recovery
- view-model fresh/stale/error และ reset countdown
- config validation และ threshold notification dedupe

### Integration

- fixture source adapters -> service -> persisted state -> UI view-model
- refresh สอง provider พร้อมกันโดยไม่มี lost update
- CLI diagnostics ไม่เปิดเผย secret

### Windows smoke

- import/compile ทุก module
- launch packaged app, ตรวจ single instance, refresh, dashboard และ clean exit
- ยืนยันว่า refresh cycle ไม่สร้าง `cmd.exe`, `conhost.exe` หรือ `agy.exe`

## 9. Acceptance criteria

- เปิดด้วย `run.bat` ได้บนเครื่องนี้และไม่มี console flash
- fresh Codex/AGY data แสดง source และเวลายืนยันได้
- เมื่อ provider ปิด/network ล้มเหลว ค่าเดิมยังอยู่พร้อม stale/error indicator ไม่กลับเป็น 100%
- token totals ของ Codex เกิดจาก local logs โดยไม่ต้องกด add manually
- tests ครอบคลุม regression หลักและผ่านทั้งหมด
- state file ยังเป็น JSON ถูกต้องหลัง concurrent updates
- idle loop ไม่ probe provider ถี่กว่า TTL และไม่ใช้ topmost loop 20Hz
- build สร้าง executable ที่รันโดยไม่ต้องพึ่ง Python ใน PATH

## 10. แหล่งแนวคิดและข้อจำกัดการนำมาใช้

- TaskbarQuota: provider registry, normalized windows, per-result TTL, last-good snapshot และ taskbar/dashboard separation
- ccusage Codex adapter: active + archived sessions, `last_token_usage` ก่อน cumulative delta และ dedupe สำเนา session
- PyInstaller: Windows onedir/windowed distribution
- Microsoft/Python docs: single-instance และ inter-process file locking

นำมาเฉพาะแนวทางและ data-shape ที่จำเป็น ไม่ copy UI/source code จากโปรเจ็กต์อื่น และรักษาขอบเขต license ของ dependency ทุกตัว
