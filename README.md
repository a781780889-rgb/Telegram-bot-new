# Telegram Professional Management Bot

بوت تيليجرام احترافي لإدارة الحسابات، الروابط، البحث، النشر، والاشتراكات.

## المميزات
- إدارة حسابات متعددة (Telethon).
- محرك بحث متقدم.
- نظام نشر وجدولة مهام.
- لوحة تحكم إدارية كاملة.
- نظام اشتراكات وباقات.
- دعم Docker و Railway.

## المتطلبات
- Python 3.12+
- PostgreSQL
- Redis

## التشغيل المحلي
1. قم بتثبيت المكتبات:
   ```bash
   pip install -r requirements.txt
   ```
2. قم بتهيئة ملف `.env` بناءً على `.env.example`.
3. قم بتشغيل البوت:
   ```bash
   python -m app.main
   ```

## التشغيل عبر Railway
1. ارفع المشروع على GitHub.
2. اربط المستودع بـ Railway.
3. أضف متغيرات البيئة (Environment Variables) في Railway.
4. سيقوم Railway تلقائياً بالبناء والتشغيل باستخدام Dockerfile.

## هيكل المشروع
- `app/bot`: يحتوي على Handlers و Keyboards و Callbacks.
- `app/database`: يحتوي على Models و Repositories.
- `app/services`: يحتوي على Business Logic لكل قسم.
- `app/config`: إعدادات المشروع.
