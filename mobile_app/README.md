# Salon Board Mobile v2 Prototype

Read-only Flutter prototype for the future offline-first Android app.

## What works

- Login through the existing `/api/login` cookie session.
- Pull sync through `/api/sync/bootstrap`.
- Local SQLite cache for masters, services, clients, appointments, and breaks.
- Seven-day calendar screen from cached data.
- Offline read after the first successful sync.
- Online/offline indicator and last sync time.

## Run

```bash
cd mobile_app
flutter pub get
flutter create --platforms=android .
flutter run --dart-define=API_BASE_URL=https://your-backend.example.com
```

Build APK:

```bash
flutter build apk --release --dart-define=API_BASE_URL=https://your-backend.example.com
```

Default API URL is `https://salon-board.onrender.com`.

## Not implemented yet

- Create/edit/delete appointments.
- Push sync.
- Conflict resolution.
- Telegram and finance features.
