# AI Usage Tracker — Problem Status

**สถานะ ณ 2026-08-10:** implementation เดิมถูกแทนด้วย production architecture ตาม [design specification](docs/superpowers/specs/2026-08-10-production-ai-usage-tracker-design.md) และ [implementation plan](docs/superpowers/plans/2026-08-10-production-ai-usage-tracker.md)

## ปัญหาของเวอร์ชันเดิม

- taskbar เรียก refresh ถี่ทุก 15 วินาทีและ reassert topmost 20 ครั้ง/วินาที
- การเขียน JSON หลายจุดไม่มี transaction จริง ทำให้ process/thread เขียนทับกันได้
- ตัวแปร freshness และ stale indicator มีอยู่แต่ UI ไม่ได้ใช้ครบ
- provider failure สามารถทำให้ค่าที่ไม่มีข้อมูลดูเหมือนเหลือ 100%
- AGY refresh เคยเปิด `agy.exe` เป็นระยะ ส่งผลให้ AGY เปิด MCP child processes และเกิด console popup
- dashboard ใช้ token/budget จำลองและการเพิ่ม token ด้วยมือ ไม่ใช่ usage จาก session จริง
- launcher พึ่ง `pythonw` ใน PATH และไม่มี build/install flow ที่ทำซ้ำได้
- single-instance แบบ PID file มี race window และ lifecycle ของ tray/taskbar แยกกัน

## สิ่งที่แก้แล้ว

- ใช้ normalized `ProviderSnapshot` กับ source/status/observed time ชัดเจน
- `UsageService` มี provider TTL, single-flight, rate-limit backoff, last-good fallback และ monotonic reset guard
- Codex token scanner อ่าน active/archived session JSONL อัตโนมัติแบบ incremental พร้อม replay dedupe
- schema v3 state ใช้ thread lock + inter-process file lock + atomic replace + corrupt backup
- taskbar/tray/dashboard ใช้ presentation model และ state ชุดเดียวกัน; Tk ทำงานเฉพาะ main thread
- ไม่มีลูป 20 Hz และ tracker ไม่เปิด AGY หรือ command shell ตามรอบ refresh
- notification dedupe ตาม `provider/window/reset/threshold`
- diagnostics whitelist field และ rotating log ไม่เผย auth values
- มี HKCU startup, `setup.ps1`, `build.ps1`, `run.bat` และ PyInstaller onedir/windowed

## Source policy ปัจจุบัน

- Codex quota: live usage API จาก auth ของ Codex CLI; เมื่อใช้ไม่ได้จะเก็บ last-good พร้อม error/stale ที่เห็นได้
- Codex tokens: local `sessions` และ `archived_sessions`
- AGY quota: local API ที่รันอยู่ จากนั้น cache และ last-good; ไม่ spawn `agy.exe`

## Acceptance status

- automated tests ครอบคลุม model, migration, concurrent state mutation, scanner, provider adapters, TTL/single-flight, UI models, diagnostics, notifications, startup และ offline integration
- PyInstaller build ผ่านและ packaged process รันจริงบน Windows 11
- state/log อยู่ใน `%LOCALAPPDATA%\AIUsageTracker` สำหรับ executable และ `data\` สำหรับ source mode
- ขั้นตอนใช้งานและ troubleshooting อยู่ใน [README.md](README.md)

เอกสาร incident เดิมถูกย่อออกเพราะมี path/account/model และคำกล่าวอ้างที่ไม่ตรงกับ implementation ปัจจุบัน หากต้องสืบประวัติให้ดู Git history ของไฟล์นี้ก่อนวันที่ 2026-08-10
