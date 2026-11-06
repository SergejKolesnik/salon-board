import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as path;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:salon_board_mobile/core/db/local_database.dart';

void main() {
  late LocalDatabase database;
  late String databasePath;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    database = LocalDatabase();
    databasePath = path.join(await getDatabasesPath(), 'salon_board_mobile.db');
    await databaseFactory.deleteDatabase(databasePath);
  });

  tearDown(() async {
    await database.close();
    await databaseFactory.deleteDatabase(databasePath);
  });

  test(
      'stores a booking locally before sync and removes it from the outbox on ack',
      () async {
    final saved = await database.saveAppointment(
      localId: null,
      serverId: null,
      masterId: 7,
      clientName: 'Олена Клієнтка',
      phone: '+380501234567',
      service: 'Чистка',
      serviceIds: [3],
      clientId: null,
      date: '2026-11-06',
      startTime: '10:30',
      durationMin: 60,
      notes: 'Перша зустріч',
      status: 'scheduled',
      baseVersion: null,
    );

    expect(await database.pendingCount(), 1);
    final local = await database.loadSchedule(
        DateTime(2026, 11, 6), DateTime(2026, 11, 6));
    expect(local.appointments.single.clientName, 'Олена Клієнтка');
    expect(local.appointments.single.isPending, isTrue);

    await database.applyPushResult({
      'mappings': {
        'appointments': [
          {
            'local_id': saved.localId,
            'server_id': 42,
            'server_version': 1,
            'action': 'create',
          },
        ],
        'breaks': [],
        'clients': [],
      },
      'errors': [],
    });

    expect(await database.pendingCount(), 0);
    final synced = await database.loadSchedule(
        DateTime(2026, 11, 6), DateTime(2026, 11, 6));
    expect(synced.appointments.single.serverId, 42);
    expect(synced.appointments.single.isPending, isFalse);
  });

  test('keeps a local edit when bootstrap contains the older server row',
      () async {
    final saved = await database.saveAppointment(
      localId: null,
      serverId: null,
      masterId: 7,
      clientName: 'Локальне ім’я',
      phone: '',
      service: 'Чистка',
      serviceIds: const [],
      clientId: null,
      date: '2026-11-06',
      startTime: '11:00',
      durationMin: 60,
      notes: '',
      status: 'scheduled',
      baseVersion: null,
    );

    await database.saveBootstrap({
      'server_time': '2026-11-06T10:00:00Z',
      'masters': const [],
      'services': const [],
      'clients': const [],
      'breaks': const [],
      'appointments': [
        {
          'id': 42,
          'uuid': saved.localId,
          'master_id': 7,
          'client_name': 'Старе ім’я з хмари',
          'service': 'Чистка',
          'service_ids': const [],
          'appt_date': '2026-11-06',
          'start_time': '11:00',
          'duration_min': 60,
          'status': 'scheduled',
          'version': 1,
        },
      ],
    });

    final local = await database.loadSchedule(
        DateTime(2026, 11, 6), DateTime(2026, 11, 6));
    expect(local.appointments.single.clientName, 'Локальне ім’я');
    expect(local.appointments.single.isPending, isTrue);
    expect(await database.pendingCount(), 1);
  });

  test(
      'records server push failures for the user and excludes them from automatic retries',
      () async {
    final saved = await database.saveAppointment(
      localId: null,
      serverId: null,
      masterId: 7,
      clientName: 'Конфлікт',
      phone: '',
      service: 'Чистка',
      serviceIds: const [],
      clientId: null,
      date: '2026-11-06',
      startTime: '11:00',
      durationMin: 60,
      notes: '',
      status: 'scheduled',
      baseVersion: null,
    );

    await database.applyPushResult({
      'mappings': {'appointments': [], 'breaks': [], 'clients': []},
      'errors': [
        {
          'type': 'appointment',
          'local_id': saved.localId,
          'detail': 'Цей час вже зайнятий у майстра',
        },
      ],
    });

    expect(await database.pendingCount(), 1);
    expect(await database.failedCount(), 1);
    expect(await database.pendingChanges(), isEmpty);
    final local = await database.loadSchedule(
        DateTime(2026, 11, 6), DateTime(2026, 11, 6));
    expect(
        local.appointments.single.syncError, 'Цей час вже зайнятий у майстра');
  });

  test('migrates the read-only v1 cache without losing cached appointments',
      () async {
    final db = await databaseFactory.openDatabase(
      databasePath,
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, _) async {
          await db.execute(
              'CREATE TABLE masters_cache (server_id INTEGER PRIMARY KEY, uuid TEXT, name TEXT, color TEXT, initials TEXT, updated_at TEXT, deleted_at TEXT, version INTEGER)');
          await db.execute(
              'CREATE TABLE services_cache (server_id INTEGER PRIMARY KEY, uuid TEXT, name TEXT, sort_order INTEGER, updated_at TEXT, deleted_at TEXT, version INTEGER)');
          await db.execute(
              'CREATE TABLE clients_cache (server_id INTEGER PRIMARY KEY, uuid TEXT, first_name TEXT, last_name TEXT, phone TEXT, birthday TEXT, telegram_chat_id TEXT, notes TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT, version INTEGER)');
          await db.execute(
              'CREATE TABLE appointments_cache (server_id INTEGER PRIMARY KEY, uuid TEXT, master_id INTEGER, client_id INTEGER, client_name TEXT, phone TEXT, service TEXT, appt_date TEXT, start_time TEXT, duration_min INTEGER, notes TEXT, status TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT, version INTEGER)');
          await db.execute(
              'CREATE TABLE breaks_cache (server_id INTEGER PRIMARY KEY, uuid TEXT, master_id INTEGER, break_date TEXT, start_time TEXT, end_time TEXT, label TEXT, updated_at TEXT, deleted_at TEXT, version INTEGER)');
          await db.execute(
              'CREATE TABLE sync_meta (key TEXT PRIMARY KEY, value TEXT)');
          await db.insert('appointments_cache', {
            'server_id': 42,
            'uuid': 'appt-42',
            'master_id': 7,
            'client_name': 'Збережений запис',
            'phone': '',
            'service': 'Чистка',
            'appt_date': '2026-11-06',
            'start_time': '11:00',
            'duration_min': 60,
            'notes': '',
            'status': 'scheduled',
            'version': 1,
          });
        },
      ),
    );
    await db.close();

    final migrated = await database.loadSchedule(
        DateTime(2026, 11, 6), DateTime(2026, 11, 6));
    expect(migrated.appointments.single.serverId, 42);
    expect(migrated.appointments.single.clientName, 'Збережений запис');
  });
}
