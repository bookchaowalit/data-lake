---
title: solo-data-lake — Product Card
doc_id: CARD-solo-data-lake
doc_type: product-card
verdict: invest
version: 0.1
date: 2026-10-11
status: ร่างเพื่อพิจารณา
owner: Product owner (Book Dev)
---

# solo-data-lake — Product Card

## 1. สรุปคุณค่าในหนึ่งประโยค

รวบรวมข้อมูล (ข่าว ตลาด SEO งาน Telegram/Brave ไดอารี) เข้า lake แบบ landing → Bronze → Silver เพื่อให้วิเคราะห์ย้อนได้จากแหล่งเดียว

## 2. ปัญหาและผู้ใช้เป้าหมาย

ข้อมูลที่เก็บมาหลายแหล่งกระจัดกระจายและไม่มี lineage ผู้ใช้คือเจ้าของและ pipeline วิเคราะห์

## 3. สิ่งที่ทำได้จริงตอนนี้

- โมดูล `infra/scripts/data_lake/` (47 modules: ingest, storage, query, silver, product_adapter, run_* capture)
- discovery/opportunities scripts, collector Telegram/Brave, dbt projection
- เทสต์ 70 ไฟล์ และ CI 5 workflow

## 4. หลักฐานสถานะ

| รายการ | ค่า |
|---|---|
| Stack | Python, Parquet, dbt |
| Commit | 75 ครั้ง (2026-07-27 ถึง 2026-10-11) |
| ซอร์สโค้ด | 124 ไฟล์ / 32342 บรรทัด |
| เทสต์ | 70 ไฟล์ (ไม่ได้รันในงานนี้) |
| CI | 5 workflow |
| Deploy config | ไม่มี deploy config (ทะเบียนระบุ exception/local) |
| Live URL | ไม่มี |

## 5. คุณค่าและจุดต่าง

- lake-first ทำให้ย้อนตรวจและสร้างผลิตภัณฑ์ข้อมูลต่อได้
- **[สมมติฐาน]** ขาย data product ได้ถ้ามีชุดข้อมูลที่มีคุณค่า

## 6. ช่องว่างสำคัญ

- โครงสร้าง `infra/...` เดิมคงไว้เพื่อให้ path ทำงาน อ่านยาก
- ข้อมูลจริงอยู่นอก repo; ไม่ยืนยันขนาดและความสดของข้อมูล **[ต้องยืนยัน]**

## 7. คำตัดสิน

**`invest`** — ฐานข้อมูลวิเคราะห์ของระบบ มีโค้ดและเทสต์มากที่สุดในกลุ่ม จะเปลี่ยนเป็น `showcase` หากเลิกเก็บข้อมูลหรือย้ายไปบริการ managed

## 8. ขั้นต่อไป

1. ยืนยันว่า CI 5 workflow รันผ่านจริง
2. จัดโครงสร้างให้พ้น path `infra/...` เมื่อพร้อม

## การอนุมัติ

| บทบาท | สถานะ | วันที่ | ลงนาม |
|---|---|---|---|
| Product owner (Book Dev) | รอพิจารณา | — | ________ |

## แหล่งข้อมูล

- `README.md`
- `infra/scripts/data_lake/`, `infra/tests/data_lake/`, `infra/dbt/`
