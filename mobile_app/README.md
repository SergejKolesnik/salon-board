# Salon Board Mobile v2 Prototype

Read-only Flutter prototype for the future offline-first Android app.

Android app name: **Body Balance CRM**.

## What works

- Login through the existing `/api/login` cookie session.
- Pull sync through `/api/sync/bootstrap`.
- Local SQLite cache for masters, services, clients, appointments, and breaks.
- Seven-day calendar screen from cached data.
- Offline read after the first successful sync.
- Online/offline indicator and last sync time.
- Sync diagnostics screen with network state, last sync, app version, local DB size, and cached row counts.

## Run

```bash
cd mobile_app
flutter pub get
flutter create --platforms=android .
flutter pub run flutter_launcher_icons
flutter pub run flutter_native_splash:create
powershell -ExecutionPolicy Bypass -File tool/configure_android.ps1
flutter run --dart-define=API_BASE_URL=https://your-backend.example.com
```

Build APK:

```bash
flutter build apk --release --dart-define=API_BASE_URL=https://your-backend.example.com
```

Debug APK for testing:

```bash
flutter build apk --debug --dart-define=API_BASE_URL=https://your-backend.example.com
```

The debug APK will be at:

```text
build/app/outputs/flutter-apk/app-debug.apk
```

Install on Android:

```bash
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

Or copy `app-debug.apk` to the phone, open it from Files, and allow install from unknown apps when Android asks.

Default API URL is `https://salon-board.onrender.com`.

## Not implemented yet

- Create/edit/delete appointments.
- Push sync.
- Conflict resolution.
- Telegram and finance features.
