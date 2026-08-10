# Right-Aligned Taskbar Text Design

## Goal

ขยับข้อความ quota ไปทางขวาให้ใกล้ system tray มากขึ้น โดยไม่ขยับหรือขยาย native overlay window และไม่บังพื้นที่คลิกของ taskbar

## Layout contract

- วัดความกว้างรวมของข้อความทุก segment ด้วย font handle เดียวกับที่ใช้วาด
- จุดเริ่มแนวนอนคือ `max(10, client_width - content_width - 12)`
- เมื่อข้อความสั้น ปลายข้อความจะอยู่ห่างขอบขวาของ overlay 12 px
- เมื่อข้อความยาวเกินพื้นที่ จะ fallback ที่ขอบซ้าย 10 px และยอมให้ painter เดิม clip ที่ client boundary
- waiting state `AI Usage — waiting for data` ใช้กฎจัดชิดขวาเดียวกัน

## Rendering boundary

- แยกการสร้างรายการ render segment ออกจากการวาด เพื่อให้วัดและวาดข้อความชุดเดียวกันโดยไม่เกิดความคลาดเคลื่อน
- segment เก็บ text, color และ horizontal gap หลัง segment
- คงข้อความ สี warning/critical, indicator, separator และ compact provider selection เดิมทั้งหมด
- ไม่เปลี่ยน overlay width, `_reposition`, taskbar owner, Z-order policy, timer หรือ non-erasing repaint

## Verification

- pure layout test: client 400 px และ content 320 px เริ่มที่ 68 px
- pure layout test: content ที่กว้างเกินพื้นที่เริ่มที่ 10 px
- render-segment test ยืนยันว่า Antigravity/Codex ยังคงข้อความและลำดับเดิม
- full pytest suite และ compile check ต้องผ่าน
- rebuild PyInstaller artifact, restart exact packaged executable และตรวจว่ามี instance เดียวพร้อม taskbar owner เดิม

## Non-goals

- ไม่ปรับระยะ 230 px ระหว่าง overlay window กับขอบ taskbar
- ไม่เปลี่ยน font, font size หรือความกว้าง 400 px
- ไม่เพิ่ม setting สำหรับกำหนด offset เอง
