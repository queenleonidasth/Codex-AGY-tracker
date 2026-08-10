# Compact Taskbar Display Design

## Goal

ย่อข้อความบน Windows taskbar ให้ไม่ล้น โดยคงเฉพาะ quota ที่ผู้ใช้ต้องการเห็นทันที

## Display contract

- Antigravity แสดงสอง window เท่านั้น: `session` เป็น `5H` และ `weekly` เป็น `W`
- Codex แสดง `weekly` เป็น `W` เพียงค่าเดียว หาก provider ไม่มี weekly จึง fallback ไปยัง `session`/window แรกที่มี
- รูปแบบเป้าหมาย: `Antigravity 94% 5H · 93% W | Codex 80% W`
- สถานะ stale/error (`~`/`!`) และสี warning/critical เดิมยังทำงาน
- กลุ่ม AGY อื่น เช่น 3P ไม่แสดงบน taskbar แต่ยังอยู่ใน Dashboard และ context menu
- taskbar overlay จำกัดความกว้าง compact ไม่เกิน 400 px; dashboard/tray ไม่เปลี่ยน

## Implementation boundary

เพิ่ม pure presentation selector ใน `ui_models.py` เพื่อเลือก window สำหรับ taskbar แล้วให้ `taskbar_widget.py` render จาก selector นี้ ห้ามกรองข้อมูลที่ provider/state เพราะ UI อื่นยังต้องใช้ข้อมูลครบ

## Tests

- AGY เลือกเฉพาะ session + weekly และเรียง 5H ก่อน W
- Codex เลือก weekly ค่าเดียวแม้มี session
- Codex fallback เมื่อไม่มี weekly
- extra AGY windows ยังคงอยู่ใน provider view สำหรับ Dashboard/context details
- full suite, PyInstaller build และ packaged smoke test ต้องผ่าน
