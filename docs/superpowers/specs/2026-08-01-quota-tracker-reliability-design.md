# Codex-AGY Tracker Reliability Design

> สถานะเอกสาร: Design approved สำหรับจัดทำเอกสาร เมื่อ 2026-08-01
>
> ขอบเขต: ความถูกต้องของ quota, background refresh, Windows process/terminal behavior, shared state และ observability
>
> Repository: `queenleonidasth/Codex-AGY-tracker`
>
> เอกสารเดิมที่ถูกแทนที่: `problem.md` ฉบับ commit `ed0e15a`

## 1. Executive summary

ระบบปัจจุบันยังไม่สามารถรับประกันได้ว่า quota ที่แสดงเป็นข้อมูลล่าสุด และยังมีเส้นทางที่สร้าง process หรือหน้าต่าง terminal ซ้ำได้ ปัญหาไม่ได้มาจากจุดเดียว แต่เกิดจากการเชื่อมกันของห้าส่วน:

1. AGY reader อ้างอิง cache file ที่ไม่มีอยู่ในเครื่องปัจจุบัน
2. refresh loop เรียก `agy.exe` ซ้ำโดยไม่มี single-flight, backoff หรือ single-instance guard
3. monotonic guard ใช้ weekly reset identity กับ quota 5 ชั่วโมง ทำให้ค่า 5h ค้างหลัง reset
4. state file ไม่มี freshness metadata, atomic write หรือ inter-process lock
5. Windows process flags, `.py` file association และ MCP command ภายนอก repo ยังสร้าง console process ได้

การแก้ที่แนะนำคือ refactor ขนาดเล็ก ไม่ rewrite ทั้งโปรเจกต์ โดยให้มี refresh service เพียงตัวเดียว, quota model ที่แยกตาม window, provider adapters ที่คืนผลแบบมี provenance, state store ที่เขียนแบบ atomic และ UI ที่แสดง stale/unavailable อย่างตรงไปตรงมา

งาน MCP `uvx.exe` เป็น workstream แยกจาก runtime ของ widget แม้มีอาการ terminal คล้ายกัน ต้องแก้ใน user configuration และทดสอบแยกกัน

## 2. เป้าหมาย

หลัง implementation เสร็จ ระบบต้องมีคุณสมบัติต่อไปนี้:

- แสดง quota ของแต่ละ provider จาก observation ล่าสุดที่ตรวจสอบ provenance และ timestamp ได้
- แยก AGY 5h กับ weekly เป็นคนละ reset window โดยสมบูรณ์
- ไม่แสดง snapshot เก่าเป็นข้อมูล fresh เมื่อ fetch ล้มเหลวหรือ source ไม่มี
- มี background refresh เพียงหนึ่งงานต่อ provider ต่อ process และมี widget เพียงหนึ่ง instance ต่อ Windows user session
- ไม่มี `cmd.exe`, `conhost.exe` หรือ Windows Terminal tab ใหม่จาก refresh cycle
- ไม่มี partial JSON, JSON decode race หรือ lost update ระหว่าง taskbar/tray/CLI
- การเลือก Codex rate-limit event อ้างอิง event timestamp ไม่ใช่ลำดับชื่อไฟล์เพียงอย่างเดียว
- ทุก regression ที่พบใน incident นี้มี automated test
- runtime state และ bytecode ไม่ถูก commit เข้า Git

## 3. สิ่งที่ไม่อยู่ในขอบเขต

- ไม่สร้าง billing system หรือคำนวณค่าใช้จ่ายจากราคา token
- ไม่ reverse-engineer private network API ของ AGY
- ไม่เปลี่ยนหน้าตา taskbar widget นอกเหนือจาก stale/unavailable indicator และชื่อ window ที่จำเป็น
- ไม่เพิ่ม provider ใหม่
- ไม่ rewrite Win32/GDI widget เป็น framework อื่น
- ไม่รวมการติดตั้ง `windows-mcp` เข้ากับ installer ของ widget เพราะเป็น configuration ของ Codex/Antigravity ภายนอก repo

## 4. หลักฐานจากระบบปัจจุบัน

การตรวจสอบนี้ทำบน Windows user `C:\Users\QUEEN` วันที่ 2026-08-01 โดยไม่เรียก AGY refresh จริง เพื่อไม่สร้างหน้าต่างรบกวนผู้ใช้

### 4.1 AGY source ไม่มีอยู่

`auto_fetch.py:21` กำหนด source เป็น:

```text
C:\Users\QUEEN\.tokentracker\tracker\agy_quota_cache.json
```

ผลตรวจ:

```text
ExpectedCacheExists : False
StatuslineExists    : False
```

ไม่พบ `agy_statusline.py` ใน `.quickwork`, `.gemini` หรือ `.codex` ด้วย ดังนั้น design เดิมที่คาดว่า `agy.exe -p /usage` จะกระตุ้น statusline hook ให้เขียน cache ไม่มี component รองรับอยู่ในเครื่องนี้

### 4.2 Snapshot ใน Git ไม่ตรงกับ Codex session จริง

`data/token_usage.json` ที่ commit ไว้ระบุ:

```json
{
  "used_percent": 17.0,
  "window_minutes": 43200,
  "plan_type": "free"
}
```

event ล่าสุดขณะตรวจระบุ:

```text
used_percent  : 19
window_minutes: 10080
plan_type     : plus
```

ความแตกต่างนี้ไม่ใช่เพียง rounding แต่เป็นทั้ง plan และชนิด window จึงห้ามใช้ runtime snapshot ที่ commit มาเป็น default ที่เชื่อถือได้

### 4.3 Monotonic guard ทำให้ 5h reset ไม่ได้

logic ปัจจุบันตรวจ `old_agy.reset_time == new_agy.reset_time` ซึ่ง `reset_time` เป็น weekly reset แล้วนำผลไป clamp `percent_5h_left` ด้วย

reproduction แบบ pure logic:

```text
old 5h remaining       = 16.5
incoming 5h remaining  = 100.0
weekly reset identity  = unchanged
accepted by guard      = 16.5
```

ดังนั้นเมื่อ 5h window เริ่มรอบใหม่ แต่ weekly window ยังเป็นรอบเดิม ค่า 5h จะถูกล็อกไว้ที่ค่าต่ำเดิม

### 4.4 Process flags ขัดกัน

`auto_fetch.py:40` ใช้ `0x08000008` ซึ่งรวม `CREATE_NO_WINDOW` และ `DETACHED_PROCESS`

Microsoft ระบุว่า `CREATE_NO_WINDOW` ถูก ignore เมื่อใช้กับ `DETACHED_PROCESS`:

- <https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags>

การใช้สอง flag พร้อมกันจึงไม่ใช่ defense-in-depth และไม่ควรเก็บเป็น magic number

### 4.5 `uvx.exe` เป็น external terminal source ที่ยัง active

`C:\Users\QUEEN\.codex\config.toml` กำหนด:

```toml
[mcp_servers.windows-mcp]
command = "uvx"
args = ["windows-mcp", "serve"]
```

ขณะตรวจพบ `uvx.exe windows-mcp serve` สาม process โดยอย่างน้อยสอง process มี `codex.exe` เป็น parent นี่เป็นคนละ process tree กับ widget และต้องแก้/verify แยกจาก `agy.exe`

### 4.6 ไม่มี automated test หรือ repository hygiene

repo ไม่มี test file, ไม่มี `.gitignore` และ track ทั้ง:

```text
__pycache__/*.pyc
data/config.json
data/token_usage.json
```

syntax parse ผ่านทั้งหกไฟล์ Python แต่ syntax success ไม่ได้พิสูจน์ behavior ของ quota, concurrency หรือ Windows process creation

## 5. Root-cause analysis

### 5.1 Quota ไม่ตรง

#### สาเหตุหลัก A: ไม่มี source contract

`fetch_agy_quota_cache()` ถือว่า cache path และ schema พร้อมใช้งาน แต่ไม่มี startup validation, version field หรือ capability detection หาก cache ไม่มี ฟังก์ชันจะพยายามสร้างมันทางอ้อมผ่าน CLI โดยไม่รู้ว่า CLI รุ่นนั้นรองรับ hook ดังกล่าวหรือไม่

#### สาเหตุหลัก B: freshness ถูกปนกับ persistence timestamp

`save_usage()` อัปเดต `last_updated` ทุกครั้ง แม้ provider ทั้งหมด fetch ไม่สำเร็จ `last_updated` จึงหมายถึง “ไฟล์ถูกเขียน” ไม่ใช่ “quota ได้รับการยืนยันจาก source”

#### สาเหตุหลัก C: window identity ไม่สมบูรณ์

AGY state เก็บ top-level `reset_time` เพียงค่าเดียว แต่แสดงทั้ง 5h และ weekly การไม่มี `reset_time` แยกสำหรับ 5h ทำให้ validation ข้าม window

#### สาเหตุหลัก D: event selection ไม่ได้เทียบ timestamp ข้ามไฟล์

Codex reader sort filename แล้วคืน rate-limit event จากไฟล์แรกที่พบ วิธีนี้พึ่งพารูปแบบชื่อไฟล์และไม่รับประกันว่าจะเลือก event timestamp สูงสุดเมื่อมีหลาย session เขียนพร้อมกัน

#### สาเหตุหลัก E: committed runtime state ถูกใช้เป็น fallback โดยไม่มี stale marker

clone ใหม่เริ่มจาก quota ของผู้สร้าง snapshot หาก fetch ไม่สำเร็จ UI จะแสดงค่าเหล่านั้นต่อไป และไม่มีข้อมูลให้ผู้ใช้แยกว่าเป็น demo, cached หรือ live

### 5.2 Terminal/process โผล่ซ้ำ

#### สาเหตุหลัก A: refresh scheduling ไม่มี single-flight

ทุก timer cycle ที่ตรงเงื่อนไขจะสร้าง daemon thread ใหม่ หากงานเก่ายังไม่เสร็จ งานใหม่จะซ้อนทันที

#### สาเหตุหลัก B: application ไม่มี single-instance guard

`run_taskbar.bat` เปิด widget instance ใหม่ทุกครั้ง แต่ละ instance มี scheduler ของตนเอง จำนวน CLI child process จึงเพิ่มเป็นสัดส่วนกับจำนวน widget instances

#### สาเหตุหลัก C: invalid source ทำให้ refresh ทุกครั้งลงท้ายด้วย CLI spawn

เพราะ cache ไม่เคยเกิด ทุก refresh มีสถานะ `needs_refresh=True` อย่างถาวร

#### สาเหตุหลัก D: Windows process creation policy ไม่เป็นหนึ่งเดียว

AGY ใช้ flags ที่ขัดกัน, dashboard ใช้ `os.startfile(.py)` และ launcher เป็น `.bat` แต่ละเส้นทางมี behavior ต่างกันตาม file association และ parent console

Python ระบุว่า `os.startfile()` เปิดไฟล์ด้วย application ที่ผูกกับ extension:

- <https://docs.python.org/3/library/os.html#os.startfile>

#### สาเหตุหลัก E: MCP command ภายนอก repo ใช้ on-demand runner

`uvx windows-mcp serve` resolve environment และสร้าง process tree ทุกครั้งที่ MCP client เริ่ม server ปัญหานี้ไม่สามารถแก้จาก `auto_fetch.py`

### 5.3 State corruption และ lost update

`auto_fetch.py`, `token_tracker.py`, taskbar, tray และ CLI สามารถแตะ JSON เดียวกัน การเขียนตรงเข้า target file โดยไม่มี lock มีสอง failure modes:

1. reader อ่านระหว่าง writer เขียนและได้ partial JSON
2. process A และ B อ่าน version เดียวกัน จากนั้นเขียนคนละ update ทำให้ update ที่เขียนก่อนสูญหาย

การ catch exception แบบเงียบทำให้อาการถูกแปลงเป็น stale data แทน error ที่สังเกตได้

## 6. ทางเลือกเชิงสถาปัตยกรรม

### ทางเลือก A: patch เฉพาะจุด

เปลี่ยน reset field, process flag และเพิ่ม lock ใน `taskbar_widget.py`

ข้อดี:

- diff เล็ก
- deploy เร็ว

ข้อเสีย:

- ยังผูกกับ undocumented cache
- state model ยังรวม provenance/freshness ไม่ได้ดี
- race ระหว่างหลาย process ยังแก้ไม่ครบ
- มีโอกาสกลับมาเกิดใหม่เมื่อ AGY schema เปลี่ยน

### ทางเลือก B: small reliability refactor — ทางเลือกที่เลือก

แยก provider adapters, quota model, refresh service และ state store โดยคง Win32/GDI UI เดิม

ข้อดี:

- แก้ต้นเหตุครบโดยไม่ rewrite UI
- แต่ละส่วนทดสอบได้โดยไม่ต้องเปิดหน้าต่างจริง
- รองรับ source unavailable และ schema change อย่างตรงไปตรงมา
- จำกัด process ownership ได้ชัดเจน

ข้อเสีย:

- มีไฟล์และ interface เพิ่ม
- ต้อง migrate state schema หนึ่งครั้ง

### ทางเลือก C: service + SQLite + packaged desktop application

ทำ background service แยก, SQLite store และ package executable แบบ windowed

ข้อดี:

- concurrency และ deployment แข็งแรงที่สุด
- เหมาะหากจะเพิ่ม provider หรือ analytics จำนวนมาก

ข้อเสีย:

- เกินขนาด use case ปัจจุบัน
- เพิ่ม installer/service lifecycle และ migration complexity

## 7. Architecture เป้าหมาย

```text
Windows timer / manual refresh
            |
            v
    RefreshCoordinator
      |            |
      v            v
  CodexSource    AgySource
      |            |
      +------v-----+
             |
       ProviderSnapshot
             |
       QuotaReconciler
             |
        AtomicStateStore
             |
      tracker.reload_if_changed()
             |
        Taskbar renderer
```

หลัก ownership:

- `RefreshCoordinator` เป็นเจ้าของ refresh cadence และ single-flight lock
- provider source มีหน้าที่อ่าน external data และ normalize เท่านั้น
- `QuotaReconciler` มีหน้าที่ตัดสิน event ordering และ reset-window transition
- `AtomicStateStore` เป็นเจ้าของ persistence, locking และ schema migration
- UI อ่าน immutable snapshot และไม่ spawn provider CLI เอง

## 8. File boundaries ที่เสนอ

### ไฟล์ใหม่

`quota_models.py`

- dataclasses/enums สำหรับ quota window, provider snapshot และ fetch status
- validation 0–100, timestamp normalization และ serialization

`quota_sources.py`

- `CodexQuotaSource`
- `AgyQuotaSource`
- ไม่มี UI, timer หรือ persistence

`refresh_service.py`

- refresh cadence
- single-flight
- timeout/backoff
- provider orchestration

`state_store.py`

- schema version
- inter-process lock
- atomic load/save
- migration จาก JSON เดิม

`tests/test_quota_reconciliation.py`

- window reset และ stale-event behavior

`tests/test_agy_source.py`

- missing cache, malformed JSON, timeout, process flags และ mtime transition

`tests/test_codex_source.py`

- timestamp selection ข้าม rollout files

`tests/test_refresh_service.py`

- single-flight, backoff และ partial provider failure

`tests/test_state_store.py`

- atomic write, migration และ concurrent update

### ไฟล์ที่แก้

`taskbar_widget.py`

- เลิกเรียก `auto_fetch.fetch_all()` โดยตรง
- เริ่ม/หยุด `RefreshCoordinator`
- เพิ่ม single-instance mutex
- render stale/unavailable state
- เปลี่ยน dashboard launch path

`token_tracker.py`

- เปลี่ยนจาก direct JSON ownership เป็น consumer ของ `AtomicStateStore`

`auto_fetch.py`

- ลดบทบาทเป็น CLI compatibility entrypoint ที่เรียก `RefreshCoordinator.refresh_now()`
- ไม่มี daemon loop ซ้ำกับ widget

`tray_widget.py`

- อ่าน snapshot ผ่าน store interface เดียวกัน
- ไม่สร้าง Tk root ใน arbitrary background thread

`data/config.json`

- ย้ายเป็น example/default configuration หรือ migrate ไป user state directory

`run_taskbar.bat`, `run_widget.bat`

- เลิกเป็น launcher หลัก หรือเปลี่ยนให้เรียก `.pyw`/windowed executable ที่ชัดเจน

`.gitignore`

- ignore bytecode, test cache และ runtime state

## 9. Data contract

### 9.1 QuotaWindow

```python
@dataclass(frozen=True)
class QuotaWindow:
    key: str
    remaining_percent: float
    used_percent: float
    window_minutes: int | None
    resets_at: datetime | None
    observed_at: datetime
    source: str
```

กฎ validation:

- `key` เป็น stable semantic key เช่น `"5h"`, `"weekly"`, `"primary"`
- `remaining_percent` ต้องเป็น finite number ช่วง 0–100
- `used_percent` derive จาก `100 - remaining_percent` เท่านั้น ไม่รับค่าอิสระจาก caller หลัง normalize
- `resets_at` เป็น UTC-aware datetime หรือ `None`
- `observed_at` ต้องเป็น UTC-aware datetime
- source ต้องบอก provenance เช่น `agy-cli-json`, `agy-cache-v1`, `codex-rollout`

### 9.2 ProviderSnapshot

```python
@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    plan_type: str | None
    windows: dict[str, QuotaWindow]
    observed_at: datetime
    source_status: SourceStatus
    error_code: str | None
```

`SourceStatus` มีค่า:

- `fresh`: fetch สำเร็จและ observation อยู่ใน freshness threshold
- `stale`: มี last-known-good แต่ refresh ล่าสุดล้มเหลวหรือเกิน threshold
- `unavailable`: ยังไม่มี last-known-good และ source ใช้ไม่ได้
- `unsupported`: CLI/schema ปัจจุบันไม่มี capability ที่ integration ต้องใช้

### 9.3 Persisted state schema

```json
{
  "schema_version": 3,
  "providers": {
    "AGY": {
      "plan_type": "Google AI Pro",
      "source_status": "fresh",
      "last_attempt_at": "2026-08-01T09:30:00Z",
      "last_success_at": "2026-08-01T09:30:00Z",
      "error_code": null,
      "windows": {
        "5h": {
          "remaining_percent": 100.0,
          "used_percent": 0.0,
          "window_minutes": 300,
          "resets_at": "2026-08-01T14:30:00Z",
          "observed_at": "2026-08-01T09:30:00Z",
          "source": "agy-cli-json"
        },
        "weekly": {
          "remaining_percent": 79.2,
          "used_percent": 20.8,
          "window_minutes": 10080,
          "resets_at": "2026-08-05T11:22:25Z",
          "observed_at": "2026-08-01T09:30:00Z",
          "source": "agy-cli-json"
        }
      }
    }
  }
}
```

`last_attempt_at` และ `last_success_at` ห้ามใช้ field เดียวกัน เพราะ failure attempt ไม่ได้ทำให้ข้อมูลเก่ากลายเป็น fresh

## 10. Reconciliation rules

การรับ incoming window ใช้ลำดับต่อไปนี้:

1. validate schema และ numeric bounds
2. ถ้าไม่มี old window ให้รับ incoming
3. ถ้า `incoming.observed_at <= old.observed_at` ให้ปฏิเสธ incoming เป็น stale event
4. ถ้า reset identity เปลี่ยน ให้รับ incoming โดยไม่ clamp
5. ถ้า reset identity เดิมและ provider contract เป็น fixed-decreasing window ให้รับ `min(old.remaining, incoming.remaining)`
6. ถ้า provider contract เป็น rolling/dynamic window ให้รับ observation ล่าสุดโดยไม่ monotonic clamp
7. derive `used_percent` ใหม่ทุกครั้งหลังตัดสิน remaining

reset identity ใช้ tuple:

```text
(window key, window_minutes, resets_at)
```

ห้ามใช้ weekly reset identity กับ 5h window

หาก `resets_at` หาย ห้ามเดาว่าเป็น window เดิม กรณีนี้ต้องใช้ observation ordering และ mark source quality ใน log

## 11. AGY source design

### 11.1 Capability detection

เมื่อเริ่ม application ให้ตรวจเพียงครั้งเดียวต่อ executable version:

- executable มีอยู่หรือไม่
- มี documented machine-readable quota output หรือไม่
- หากใช้ cache: configured path มีอยู่, schema version อ่านได้ และ cache มี observation timestamp หรือไม่

ผล capability ถูก cache ใน memory และประเมินใหม่เมื่อ executable mtime/version เปลี่ยน

### 11.2 Source priority

ลำดับที่ยอมรับ:

1. documented structured CLI output
2. documented/versioned cache file
3. last-known-good snapshot ที่ถูก mark `stale`
4. `unsupported` หรือ `unavailable`

ห้ามใช้ human-formatted CLI output ที่ parser ต้องเดาจากตำแหน่งข้อความ หาก AGY ไม่มี structured source ระบบต้องแสดง unavailable แทนการสร้างเปอร์เซ็นต์ที่ดูน่าเชื่อถือแต่ตรวจสอบไม่ได้

### 11.3 Process execution policy

เมื่อจำเป็นต้องเรียก AGY บน Windows:

```python
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = subprocess.SW_HIDE

subprocess.Popen(
    argv,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    startupinfo=startupinfo,
    creationflags=subprocess.CREATE_NO_WINDOW,
    text=True,
    encoding="utf-8",
)
```

ข้อกำหนด:

- ใช้ argv list ไม่ผ่าน shell
- ไม่ใช้ `DETACHED_PROCESS`
- capture stdout/stderr แบบมี size limit เพื่อวินิจฉัย error
- ใช้ `communicate(timeout=...)`
- timeout แล้ว terminate, รอ grace period, จากนั้น kill เฉพาะเมื่อยังไม่หยุด
- log duration, exit code และ error category โดยไม่ log credential
- failure ต่อเนื่องใช้ exponential backoff เช่น 15s, 30s, 60s, สูงสุด 5 นาที
- manual refresh สามารถ bypass schedule ได้ แต่ยังต้องผ่าน single-flight lock

### 11.4 Cache refresh condition

หาก structured source เป็น cache:

- บันทึก initial mtime และ content fingerprint
- trigger refresh หนึ่งครั้ง
- poll จน mtime/fingerprint เปลี่ยนและ JSON parse ผ่าน
- ใช้ deadline ไม่ใช้ fixed `sleep(2.5)`
- หาก deadline หมด ให้คืน timeout และเก็บ last-known-good เป็น stale

## 12. Codex source design

### 12.1 Event discovery

- ค้น session directories ย้อนหลังตาม UTC และ local date เพื่อครอบคลุมช่วงข้ามเที่ยงคืน
- พิจารณา rollout files ที่แก้ไขใน lookback window
- scan rate-limit events แล้ว normalize timestamp ทุก event
- เลือก event ที่ timestamp สูงสุด ไม่ใช่ไฟล์ชื่อสูงสุดเพียงอย่างเดียว
- หาก timestamp เท่ากัน ใช้ file mtime และ line ordinal เป็น deterministic tie-breaker

### 12.2 Window mapping

- map `primary` และ `secondary` เป็นคนละ window เมื่อมีทั้งคู่
- label จาก `window_minutes` เช่น 300 นาทีเป็น 5h และ 10080 นาทีเป็น weekly
- ไม่ hardcode ว่า primary แปลว่า 5h เสมอ
- เก็บ `limit_id`, `limit_name` และ plan type เพื่อ debug schema change

### 12.3 Staleness

rollout source เป็น passive observation หากไม่มี event ใหม่ ระบบยังแสดง last-known-good ได้ แต่ต้องเปลี่ยนเป็น stale หลัง threshold ที่กำหนด ไม่เขียน timestamp ปัจจุบันทับ event timestamp

## 13. RefreshCoordinator design

state machine:

```text
IDLE -> FETCHING -> SUCCESS -> IDLE
                  -> PARTIAL_SUCCESS -> BACKOFF
                  -> FAILURE -> BACKOFF
BACKOFF -> FETCHING เมื่อ deadline ถึงหรือ manual refresh
```

ข้อกำหนด:

- ใช้ worker thread เดียว
- request ระหว่าง `FETCHING` ถูก coalesce เป็น pending refresh เดียว
- provider fetch สามารถ fail แยกกัน Codex สำเร็จต้องไม่ถูกทิ้งเพราะ AGY ล้มเหลว
- UI timer มีหน้าที่อ่าน snapshot/repaint เท่านั้น
- cadence อ้างอิง `time.monotonic()` เพื่อไม่พังเมื่อ system clock เปลี่ยน
- shutdown ส่ง event และรอ worker จบภายในเวลาจำกัด
- coordinator ไม่เขียน UI จาก worker thread แต่แจ้ง dirty state ให้ message loop

refresh interval เริ่มต้นที่ 60 วินาทีสำหรับ external CLI และสามารถตั้งค่าได้ ช่วง 3 วินาทีของ UI repaint ไม่ควรเท่ากับ external fetch cadence

## 14. Single-instance และ process ownership

taskbar widget สร้าง named mutex ระดับ user session เช่น:

```text
Local\CodexAGYTracker.Taskbar.<user-sid>
```

หาก `GetLastError() == ERROR_ALREADY_EXISTS` instance ใหม่ต้อง exit โดยไม่เริ่ม refresh worker

Microsoft อธิบาย named mutex สำหรับ single-instance application ที่:

- <https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexa>

state writer ใช้ mutex แยกชื่อ:

```text
Local\CodexAGYTracker.State.<user-sid>
```

ต้องเก็บ mutex handle ไว้ตลอด lifetime ที่ต้องการ ownership และปิด handle ตอน shutdown

## 15. State store และ filesystem policy

### 15.1 Runtime location

runtime state ย้ายไป:

```text
%LOCALAPPDATA%\CodexAGYTracker\state.json
%LOCALAPPDATA%\CodexAGYTracker\config.json
%LOCALAPPDATA%\CodexAGYTracker\logs\tracker.log
```

repo เก็บเพียง `data/config.example.json`

### 15.2 Atomic write

ลำดับ write:

1. acquire inter-process state lock
2. load current schema ล่าสุดภายใต้ lock
3. apply mutation
4. serialize ไป temp file ใน directory เดียวกัน
5. flush และ `os.fsync()`
6. `os.replace(temp, state.json)`
7. release lock

temp file ต้องอยู่ volume เดียวกับ target เพื่อให้ replace เป็น atomic

### 15.3 Migration

เมื่อพบ legacy `data/token_usage.json`:

- import token totals ได้
- import quota ได้เฉพาะเป็น `stale` และ source `legacy-repo-snapshot`
- ไม่ตั้ง `last_success_at` เป็นเวลาปัจจุบัน
- หลัง migration เขียน `schema_version: 3`
- migration ซ้ำต้อง idempotent

## 16. UI behavior

ตัวอย่างการแสดงผล:

```text
AGY 16.5% · 79.2%       fresh
AGY 16.5% · 79.2% ~     stale
AGY -- · --             unavailable/unsupported
Codex 81.0%             fresh
```

กฎ:

- `~` หรือ visual indicator ที่กำหนดชัดเจนหมายถึง stale
- tooltip/dashboard แสดง `last_success_at`, source และ error summary
- UI ห้ามแทน missing quota ด้วย 100%
- fallback monthly token budget ต้องมี label ต่างจาก provider quota ไม่ใช้พื้นที่/ความหมายเดียวกันแบบเงียบ ๆ
- 5h และ weekly ต้องมี label ใน dashboard แม้ taskbar ใช้ตำแหน่งคงที่

## 17. Dashboard launch และ Tk lifecycle

ทางเลือกที่แนะนำระยะนี้:

- ให้ tray application เป็น windowed process เดียวของ dashboard
- taskbar ขอเปิด dashboard ผ่าน IPC เบา ๆ หรือเปิด existing tray instance
- tray มี single-instance mutex ของตัวเอง
- Tk root และ `mainloop()` อยู่ main thread ของ tray process

หากยังต้อง spawn tray:

- resolve `pythonw.exe` จาก interpreter installation อย่างชัดเจน
- เรียก `.pyw` หรือ module ด้วย argv list
- ใช้ `CREATE_NO_WINDOW`
- ไม่ใช้ `os.startfile()` กับ `.py`

batch file ใช้ได้เป็น developer convenience แต่ production launch ควรเป็น shortcut ไป `pythonw.exe` หรือ packaged windowed executable เพื่อไม่มี batch-console flash

## 18. External MCP/uvx workstream

งานนี้ deploy แยกจาก repo และมี acceptance test ของตัวเอง

ขั้นตอนออกแบบ:

1. ติดตั้ง `windows-mcp` แบบ persistent tool แทน ephemeral `uvx`
2. resolve executable path จาก tool manager หลังติดตั้ง
3. เปลี่ยน `C:\Users\QUEEN\.codex\config.toml` ให้ `command` เป็น absolute path
4. restart Codex แล้วตรวจ process tree
5. ยืนยันว่ามี MCP server ต่อ Codex instance ตามจำนวนที่คาด และไม่มี Windows Terminal tab ใหม่

ห้ามใช้ path ใต้ `uv\cache\archive-*` เป็น permanent command เพราะ cache hash เปลี่ยนได้

หาก persistent executable ยังสร้าง console tab ต้องพิจารณา supported HTTP transport หรือ launcher ที่รักษา stdio pipes โดยไม่สร้าง console window การใช้ `pythonw.exe` โดยไม่ทดสอบ MCP stdio ไม่ถือว่าแก้สำเร็จ

## 19. Error taxonomy และ observability

error codes ขั้นต่ำ:

```text
SOURCE_NOT_FOUND
SOURCE_UNSUPPORTED
SOURCE_SCHEMA_INVALID
SOURCE_TIMEOUT
SOURCE_EXIT_NONZERO
SOURCE_STALE_EVENT
STATE_READ_FAILED
STATE_WRITE_FAILED
STATE_LOCK_TIMEOUT
```

log event ตัวอย่าง:

```json
{
  "event": "provider_refresh_finished",
  "provider": "AGY",
  "status": "stale",
  "error_code": "SOURCE_TIMEOUT",
  "duration_ms": 2504,
  "child_pid": 1234,
  "attempt": 2,
  "next_retry_seconds": 30
}
```

ข้อกำหนด log:

- rotating file log
- default level INFO
- ไม่เขียน prompt, access token, environment dump หรือ full session content
- debug mode เก็บ source filename และ schema keys ได้ แต่ไม่เก็บ sensitive payload
- exception ที่ boundary ห้าม `pass` เงียบ ต้อง map เป็น error code และ log

## 20. Configuration contract

ตัวอย่าง config:

```json
{
  "schema_version": 1,
  "refresh": {
    "ui_interval_ms": 3000,
    "provider_interval_seconds": 60,
    "max_backoff_seconds": 300,
    "command_timeout_seconds": 10
  },
  "agy": {
    "executable": null,
    "source": "auto",
    "cache_path": null
  },
  "codex": {
    "home": null,
    "lookback_days": 8,
    "stale_after_seconds": 300
  }
}
```

`null` หมายถึง resolve จาก documented environment/default path ไม่ใช่ hardcoded username

invalid config ต้องหยุดเฉพาะ component ที่เกี่ยวข้องและแสดง error ชัดเจน ไม่ reset quota เป็น 100%

## 21. Test strategy

### 21.1 Unit tests

Quota reconciliation:

- same 5h reset + incoming quota สูงขึ้นจาก stale pass → คงค่าต่ำเดิม
- 5h reset เปลี่ยน + weekly reset เดิม → รับ 5h ค่าใหม่
- weekly reset เปลี่ยน + 5h reset เดิม → รับ weekly ค่าใหม่โดยไม่กระทบ 5h
- incoming observation เก่ากว่า → reject
- NaN, infinity, ต่ำกว่า 0, สูงกว่า 100 → invalid
- used percent derive ตรงกับ remaining เสมอ

AGY source:

- executable ไม่มี → `SOURCE_NOT_FOUND`, ไม่มี `Popen`
- cache path ไม่มีและไม่มี structured CLI capability → `SOURCE_UNSUPPORTED`, ไม่มี retry storm
- malformed cache → `SOURCE_SCHEMA_INVALID`, last-known-good stale
- process timeout → terminate/kill policy ทำงานหนึ่งครั้ง
- process flags มี `CREATE_NO_WINDOW` และไม่มี `DETACHED_PROCESS`
- cache mtime ไม่เปลี่ยนก่อน deadline → timeout
- cache เปลี่ยนและ JSON valid → fresh snapshot

Codex source:

- หลายไฟล์ชื่อไม่เรียงกับ event timestamp → เลือก timestamp ล่าสุด
- event อยู่คนละ UTC/local date directory → ยังพบ
- primary/secondary ถูกเก็บแยก window
- malformed JSONL line ไม่ทำให้ event ที่ valid หาย

State store:

- reader เห็น old หรือ new complete JSON เท่านั้น
- concurrent token update กับ quota update ไม่สูญหาย
- legacy migration ทำซ้ำให้ผลเหมือนเดิม
- lock timeout คืน error ที่จำแนกได้

Refresh service:

- refresh request 20 รายการระหว่าง fetching → provider ถูกเรียกครั้งเดียวและมี pending run สูงสุดหนึ่งครั้ง
- AGY fail แต่ Codex success → persist Codex และ mark AGY stale
- backoff เพิ่มตาม failure และ reset หลัง success
- shutdown ไม่ทิ้ง orphan child process

### 21.2 Windows integration tests

- เปิด taskbar สองครั้ง → มี widget/refresh worker เพียง instance เดียว
- refresh AGY สิบ cycle → process monitor ไม่พบ console/Terminal window ใหม่
- เปิด dashboardสิบครั้ง → tray process ไม่ทวีจำนวน
- manual refresh ระหว่าง scheduled refresh → AGY child process สูงสุดหนึ่งตัว
- kill child CLI กลางคัน → UI ยังทำงานและแสดง stale

### 21.3 Acceptance criteria

งานถือว่าผ่านเมื่อ:

- regression 5h reset มี automated test ที่ fail บนโค้ดเดิมและ pass บนโค้ดใหม่
- missing AGY source ไม่สร้าง child process ซ้ำ
- ไม่มี `except Exception: pass` ใน provider, scheduler และ state boundaries
- state file มี per-provider freshness/provenance
- Git ไม่ track runtime state หรือ bytecode
- test suite ผ่านบน Python version ที่กำหนดและ Windows 11
- manual process observation ยืนยันว่าไม่มี terminal popup จาก widget
- external MCP observation ยืนยันผลแยกต่างหาก

## 22. Rollout และ migration strategy

### ระยะที่ 1: Safety stop

- ปิด retry storm เมื่อ AGY source ไม่มี
- แก้ process flags
- เพิ่ม single-flight และ single-instance
- เพิ่ม stale/unavailable display

ผลลัพธ์ระยะนี้ต้อง deploy ได้เองและหยุด terminal multiplication ก่อน

### ระยะที่ 2: Correct quota model

- เพิ่ม per-window reset identity
- เพิ่ม reconciliation tests
- เปลี่ยน Codex event selection
- เพิ่ม freshness/provenance schema

ผลลัพธ์ระยะนี้แก้ quota correctness โดยไม่พึ่ง UI redesign

### ระยะที่ 3: Durable state

- atomic store และ inter-process lock
- runtime directory migration
- repository cleanup

### ระยะที่ 4: Launcher และ external MCP

- dashboard lifecycle/single-instance
- windowed launcher
- persistent `windows-mcp` command และ process-tree verification

แต่ละระยะต้องมี commit/test gate แยก เพื่อย้อนกลับเฉพาะส่วนได้

## 23. ความเสี่ยงและมาตรการลดความเสี่ยง

### AGY ไม่มี structured quota source

มาตรการ: แสดง unsupported อย่างตรงไปตรงมา เก็บ last-known-good เป็น stale และไม่ parse human output แบบเปราะบาง

### Provider quota เป็น rolling window

มาตรการ: monotonic policy เป็น capability ต่อ window ไม่ใช้เป็น global assumption

### Windows executable behavior ต่างตาม installation

มาตรการ: integration test บน `python.exe`, `pythonw.exe`, direct executable และ packaged build โดยดู process tree จริง

### State migration ทำให้ผู้ใช้เสีย token history

มาตรการ: import legacy totals แบบ idempotent, สำรอง legacy file ก่อน migration และไม่ลบ source ใน release แรก

### Multiple UI processes ยังจำเป็น

มาตรการ: แยก named mutex ต่อ application role และใช้ state mutex สำหรับ shared mutation

## 24. Design decisions ที่ยืนยันแล้ว

- เลือก small reliability refactor แทน quick patch หรือ full rewrite
- UI Win32/GDI เดิมยังอยู่
- quota window ต้องมี reset identity และ observation timestamp ของตัวเอง
- source failure ต้องแสดง stale/unavailable ไม่ใช้ 100% default
- external CLI refresh ใช้ worker เดียวและ backoff
- Windows child process ใช้ `CREATE_NO_WINDOW` โดยไม่รวม `DETACHED_PROCESS`
- runtime state ย้ายออกจาก repo
- MCP `uvx` เป็น external workstream และไม่ถือว่าแก้ได้ด้วยการเปลี่ยน widget code

## 25. Self-review

- Scope ครอบคลุม quota correctness, terminal behavior, shared state, tests และ external MCP โดยแยก ownership ชัดเจน
- ไม่มี field/interface ที่ใช้ชื่อ reset เดียวร่วมกันระหว่าง 5h และ weekly
- freshness timestamp แยก attempt กับ success แล้ว
- architecture ไม่บังคับ AGY private API และมี behavior ที่ปลอดภัยเมื่อ source unsupported
- rollout แบ่งเป็น deliverable ที่ test และย้อนกลับได้
- ไม่มี placeholder หรือ requirement ที่ปล่อยให้ตีความว่า missing source เท่ากับ quota 100%
