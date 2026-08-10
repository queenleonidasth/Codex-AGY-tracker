# Flicker-Free Taskbar Overlay Design

## Goal

หยุดอาการ taskbar overlay หายชั่วคราวหรือกระพริบเมื่อผู้ใช้คลิก Start, ไอคอน, พื้นที่ว่างบน taskbar หรือเมื่อ quota อัปเดต

## Root cause

- overlay ปัจจุบันเป็น topmost popup อิสระ เมื่อ Explorer/taskbar เปลี่ยนลำดับหน้าต่างจากการคลิก overlay อาจถูกบังจน timer เรียก `SetWindowPos(HWND_TOPMOST)` รอบถัดไป
- timer ย้ำ Z-order ทุก 5 วินาทีและ reposition ทุก 10 วินาทีแม้ geometry ไม่เปลี่ยน ทำให้เกิด compositor/window-position churn
- quota update เรียก `InvalidateRect(..., TRUE)` ซึ่งร้องขอ background erase ก่อน `WM_PAINT` ทั้งที่ painter ใช้ double buffer อยู่แล้ว

## Window ownership and positioning

- ตอนสร้าง `WS_POPUP` ให้ส่ง handle ของ `Shell_TrayWnd` เป็น owner ผ่าน `CreateWindowExW`
- ไม่ใช้ `WS_EX_TOPMOST` กับ overlay ที่มี taskbar เป็น owner
- `_reposition` เปลี่ยนเฉพาะตำแหน่งและขนาดโดยใช้ `SWP_NOZORDER | SWP_NOACTIVATE`
- timer ห้ามเรียก `_reposition` หรือ `SetWindowPos` เพื่อย้ำ Z-order ตามจำนวน tick
- ยัง reposition เมื่อได้รับ `WM_DISPLAYCHANGE`, `WM_SETTINGCHANGE` หรือ `WM_DPICHANGED`
- หากหา `Shell_TrayWnd` ไม่พบตอนสร้าง ให้ `_create_window` คืน `False` และออกอย่างสะอาด แทนการสร้าง standalone popup ที่กลับไปมีปัญหา Z-order เดิม

## Painting

- เมื่อ presentation fingerprint เปลี่ยน ให้อัปเดต `_runtime.view` แล้วเรียก `InvalidateRect(hwnd, None, FALSE)`
- คง memory DC/compatible bitmap และ `BitBlt` เดิมเพื่อให้หนึ่งเฟรมถูกนำขึ้นจอพร้อมกัน
- `WM_ERASEBKGND` ยังคง return nonzero เพื่อไม่ให้ `DefWindowProc` ใช้ class background brush ล้างเฟรมที่แสดงอยู่
- ข้อมูล quota, สี, compact window selection และตำแหน่งแนวนอนปัจจุบันไม่เปลี่ยนในงานนี้

## Verification

- regression test เรียก timer handler ด้วย view เดิมและยืนยันว่าไม่มี `SetWindowPos` หรือ reposition
- regression test เรียก timer handler ด้วย view ใหม่และยืนยันว่า `InvalidateRect` รับ `bErase=FALSE`
- regression test ยืนยันว่า owner handle ถูกส่งให้ popup creation เมื่อหา taskbar พบ
- full pytest suite และ compile check ต้องผ่าน
- rebuild PyInstaller artifact, restart exact packaged executable และตรวจว่ามี instance เดียว
- manual smoke: คลิก Start, pinned icons และพื้นที่ว่างบน taskbar ต่อเนื่อง พร้อม trigger quota refresh; overlay ต้องไม่หายรอ timer แล้วกลับมา

## Non-goals

- ไม่เปลี่ยนข้อความ Antigravity/Codex
- ไม่เปลี่ยนความกว้าง overlay
- ไม่รวมการจัดข้อความชิดขวาหรือการเปลี่ยน offset
