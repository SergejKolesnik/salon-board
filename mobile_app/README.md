# Body Balance CRM для Android

Flutter-застосунок для роботи з розкладом косметологічного кабінету. Телефон зберігає календар у SQLite і є швидким робочим інтерфейсом; хмара синхронізує його з вебзастосунком та іншими пристроями.

## Як працює

- Застосунок автоматично відкриває профіль єдиного активного майстра й завантажує календар без форми пароля. Перший запуск потребує мережі.
- Запис, редагування чи блокування спершу атомарно зберігається в SQLite разом із чергою відправлення. Підтвердження в інтерфейсі означає, що дані вже на телефоні.
- Синхронізація запускається після збереження, відновлення мережі, повернення в застосунок або вручну. Повторне надсилання безпечне; конфлікт версій показується окремо.
- Неуспішні зміни залишаються на телефоні й відображаються як такі, що потребують уваги. У мобільному застосунку немає виходу чи перемикання профілю.
- Перший запуск і первинне завантаження потребують мережі. Після цього календар і нові записи доступні офлайн.

## Автоматичний мобільний доступ

Мобільний endpoint створює сесію лише для одного активного майстра, ніколи для адміністратора. Коли майстрів нуль або більше одного, автоматичний доступ зупиняється.

Це прибирає пароль із APK, але мобільний endpoint є публічним: людина, яка знає адресу сервера, може відкрити розклад і змінювати дані в межах прав цього майстра. Не використовуйте такий режим для кількох майстрів або якщо потрібна приватність від сторонніх користувачів. Вебадмінка й її пароль залишаються захищеними.

## Локальний запуск

Потрібні Flutter stable, Android SDK і Android toolchain.

```bash
cd mobile_app
flutter create --platforms=android .
flutter pub get
dart run flutter_launcher_icons
dart run flutter_native_splash:create
powershell -ExecutionPolicy Bypass -File tool/configure_android.ps1
flutter run --dart-define=API_BASE_URL=https://salon-board.onrender.com
```

## Перевірки

```bash
cd mobile_app
dart format lib test
flutter analyze --fatal-infos
flutter test
```

Python-перевірки контракту API запускаються з кореня репозиторію:

```bash
python -m py_compile main.py
python -m unittest discover -s tests
```

GitHub Actions виконує перевірки Flutter і Python та збирає APK у кожному PR. APK доступний як артефакт запуску workflow; номер запуску й спроби входить у назву ZIP та APK.

## Збірка APK

```bash
cd mobile_app
flutter create --platforms=android .
flutter pub get
dart run flutter_launcher_icons
dart run flutter_native_splash:create
powershell -ExecutionPolicy Bypass -File tool/configure_android.ps1
flutter build apk --release --dart-define=API_BASE_URL=https://salon-board.onrender.com
```

Файл: `mobile_app/build/app/outputs/flutter-apk/app-release.apk`.

Збірка CI підписана тимчасовим ключем і призначена для тестової інсталяції. Щоб оновити вже встановлений APK без видалення, потрібен той самий Android package ID та підписний ключ, якими був підписаний старий APK. У цьому репозиторії їх наразі немає. Не видаляйте старий APK, доки не перевірено встановлення/збереження потрібного профілю; старий застосунок не зберігав нових офлайн-записів, тож його кеш можна відновити з хмари після входу.

За замовчуванням API: `https://salon-board.onrender.com`.
