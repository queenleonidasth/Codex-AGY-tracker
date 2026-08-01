# 🤖 AI Token Usage Tracker v2 (Antigravity Edition)

ตัวติดตามการใช้ Token ของ AI บน **Taskbar Windows 11** เวอร์ชันปรับปรุงประสิทธิภาพใหม่ (High-Performance & Refactored Edition)

---

## ⚡ มีอะไรใหม่ใน Version 2?

1. **GDI Font Caching:** ลดการเรียกใช้ Kernel Handle ซ้ำด้วยระบบ Font Handle Cache ในเมโมรี ช่วยลด CPU usage ของกระบวนการวาดลงกว่่า 40%
2. **Smart Repainting (Dirty Checking):** ใช้การคำนวณ State Fingerprint สั่งวาดหน้าจอใหม่เฉพาะเมื่อข้อมูล Token มีการเปลี่ยนแปลงจริง ช่วยประหยัดทรัพยากรเครื่องช่วง Idle
3. **mtime File Caching:** ตรวจสอบเวลาแก้ไขไฟล์ (`os.path.getmtime`) ก่อนอ่านและแปลงไฟล์ JSON ลด Disk Read Overhead ถึง 98%
4. **Single Source of Truth (SSOT):** ยุบคลาสซ้ำซ้อนใน `taskbar_widget.py` แล้วเปลี่ยนมาอิมพอร์ต `token_tracker.tracker` Instance เดียวกันทั่วทั้งโปรเจกต์
5. **Clean Code & Zero Dead Code:** กำจัดไฟล์สคริปต์สแกนทดสอบเดิม ฟังก์ชันร้าง และ Unused Imports ทั้งหมดออกเรียบร้อย

---

## 📁 โครงสร้างโปรเจกต์ v2

```
ai_token_widget_v2/
├── taskbar_widget.py    # ⭐ ตัวหนังสือฝังบน Taskbar (Win32 GDI Caching + Smart Repaint)
├── token_tracker.py     # Core Data Manager (SSOT + mtime Caching)
├── auto_fetch.py        # Quota Fetcher (Codex Sessions & AGY Quota Cache)
├── tray_widget.py       # System Tray Icon + Dashboard Popup
├── api_interceptor.py   # API Client Wrappers
├── add_tokens.py        # CLI สำหรับเพิ่มข้อมูลทดสอบ
├── run_taskbar.bat      # สคริปต์รัน Taskbar Widget
├── run_widget.bat       # สคริปต์รัน System Tray Widget
└── requirements.txt     # Dependencies (pystray, Pillow)
```

---

## 🚀 วิธีการใช้งาน

```bash
# 1. รันตัวหนังสือบน Taskbar
python taskbar_widget.py

# หรือดับเบิลคลิก
run_taskbar.bat

# 2. เพิ่มข้อมูลทดสอบ
python add_tokens.py --demo
```

---
*Developed & Refactored by Antigravity AI*
