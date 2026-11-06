import 'dart:convert';
import 'dart:io';

import 'package:intl/intl.dart';
import 'package:path/path.dart' as path;
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import '../../features/calendar/calendar_models.dart';

/// Local source of truth for the mobile calendar and its durable sync queue.
class LocalDatabase {
  LocalDatabase({Uuid? uuid}) : _uuid = uuid ?? const Uuid();

  static const _databaseVersion = 2;

  final Uuid _uuid;
  Database? _database;
  String? _databasePath;

  Future<Database> get database async {
    final existing = _database;
    if (existing != null) return existing;

    final dbPath = await getDatabasesPath();
    final fullPath = path.join(dbPath, 'salon_board_mobile.db');
    final db = await openDatabase(
      fullPath,
      version: _databaseVersion,
      onCreate: _createSchema,
      onUpgrade: _upgradeSchema,
    );
    _databasePath = fullPath;
    _database = db;
    return db;
  }

  /// Saves a full server snapshot while retaining edits waiting in the outbox.
  Future<void> saveBootstrap(Map<String, dynamic> payload) async {
    final db = await database;
    await db.transaction((txn) async {
      await _upsertReferenceRows(txn, 'masters_cache', payload['masters']);
      await _upsertReferenceRows(txn, 'services_cache', payload['services']);
      await _upsertReferenceRows(txn, 'clients_cache', payload['clients']);
      await _applyRemoteRows(
        txn,
        'appointments',
        payload['appointments'],
      );
      await _applyRemoteRows(txn, 'breaks', payload['breaks']);
      await _putMeta(
          txn, 'last_sync_at', payload['server_time']?.toString() ?? '');
    });
  }

  /// Applies a delta response without replacing any record with pending edits.
  Future<void> applyPull(Map<String, dynamic> payload) async {
    final changes = payload['changes'] as Map? ?? const {};
    final db = await database;
    await db.transaction((txn) async {
      await _upsertReferenceRows(txn, 'masters_cache', changes['masters']);
      await _upsertReferenceRows(txn, 'services_cache', changes['services']);
      await _upsertReferenceRows(txn, 'clients_cache', changes['clients']);
      await _applyRemoteRows(txn, 'appointments', changes['appointments']);
      await _applyRemoteRows(txn, 'breaks', changes['breaks']);
      await _putMeta(
          txn, 'last_sync_at', payload['server_time']?.toString() ?? '');
    });
  }

  Future<CachedSchedule> loadSchedule(DateTime start, DateTime end) async {
    final db = await database;
    final fmt = DateFormat('yyyy-MM-dd');
    final startIso = fmt.format(start);
    final endIso = fmt.format(end);
    final appointmentRows = await db.rawQuery(
      '''SELECT a.*, p.error_text AS sync_error, p.remote_json AS remote_json,
                CASE WHEN p.id IS NULL THEN 0 ELSE 1 END AS is_pending
         FROM appointments_cache a
         LEFT JOIN pending_changes p ON p.entity_type='appointments' AND p.local_id=a.local_id
         WHERE a.appt_date >= ? AND a.appt_date <= ? AND a.deleted_at IS NULL
         ORDER BY a.appt_date, a.start_time, a.local_id''',
      [startIso, endIso],
    );
    final breakRows = await db.rawQuery(
      '''SELECT b.*, p.error_text AS sync_error, p.remote_json AS remote_json,
                CASE WHEN p.id IS NULL THEN 0 ELSE 1 END AS is_pending
         FROM breaks_cache b
         LEFT JOIN pending_changes p ON p.entity_type='breaks' AND p.local_id=b.local_id
         WHERE b.break_date >= ? AND b.break_date <= ? AND b.deleted_at IS NULL
         ORDER BY b.break_date, b.start_time, b.local_id''',
      [startIso, endIso],
    );

    return CachedSchedule(
      appointments: appointmentRows.map(CalendarAppointment.fromDb).toList(),
      breaks: breakRows.map(CalendarBreak.fromDb).toList(),
    );
  }

  Future<List<ServiceOption>> loadServices() async {
    final db = await database;
    final rows = await db.query(
      'services_cache',
      where: 'deleted_at IS NULL',
      orderBy: 'sort_order, server_id',
    );
    return rows.map(ServiceOption.fromDb).toList();
  }

  Future<List<ClientOption>> searchClients(String query) async {
    final db = await database;
    final normalized = '%${query.trim()}%';
    final rows = await db.query(
      'clients_cache',
      where:
          "deleted_at IS NULL AND (first_name LIKE ? OR last_name LIKE ? OR phone LIKE ?)",
      whereArgs: [normalized, normalized, normalized],
      orderBy: 'first_name, last_name',
    );
    return rows.map(ClientOption.fromDb).toList();
  }

  Future<List<Map<String, Object?>>> loadMasters() async {
    final db = await database;
    return db.query('masters_cache',
        where: 'deleted_at IS NULL', orderBy: 'server_id');
  }

  /// Writes a booking and its outbox mutation atomically before the UI confirms.
  Future<CalendarAppointment> saveAppointment({
    required String? localId,
    required int? serverId,
    required int masterId,
    required String clientName,
    required String phone,
    required String service,
    required List<int> serviceIds,
    required int? clientId,
    required String date,
    required String startTime,
    required int durationMin,
    required String notes,
    required String status,
    required int? baseVersion,
  }) async {
    final db = await database;
    final key = localId ?? _uuid.v4();
    final mutationId = _uuid.v4();
    final isCreate = serverId == null;
    final values = <String, Object?>{
      'local_id': key,
      'server_id': serverId,
      'uuid': key,
      'master_id': masterId,
      'client_id': clientId,
      'client_name': clientName.trim(),
      'phone': phone.trim(),
      'service': service.trim(),
      'service_ids': jsonEncode(serviceIds),
      'appt_date': date,
      'start_time': startTime,
      'duration_min': durationMin,
      'notes': notes.trim(),
      'status': status,
      'deleted_at': null,
      'version': baseVersion ?? 0,
    };
    await db.transaction((txn) async {
      await txn.insert(
        'appointments_cache',
        values,
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
      final pending = await txn.query(
        'pending_changes',
        columns: ['action'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['appointments', key],
        limit: 1,
      );
      final action = isCreate ||
              (pending.isNotEmpty && pending.first['action'] == 'create')
          ? 'create'
          : 'update';
      final data = <String, Object?>{
        'uuid': key,
        'master_id': masterId,
        'client_id': clientId,
        'client_name': clientName.trim(),
        'phone': phone.trim(),
        'service': service.trim(),
        'service_ids': serviceIds,
        'appt_date': date,
        'start_time': startTime,
        'duration_min': durationMin,
        'notes': notes.trim(),
        'status': status,
        'version': baseVersion,
      };
      await _putPending(
        txn,
        entityType: 'appointments',
        localId: key,
        serverId: serverId,
        action: action,
        mutationId: mutationId,
        baseVersion: baseVersion,
        data: data,
      );
    });
    return CalendarAppointment(
      localId: key,
      serverId: serverId,
      masterId: masterId,
      clientId: clientId,
      clientName: clientName.trim(),
      service: service.trim(),
      serviceIds: serviceIds,
      date: date,
      startTime: startTime,
      durationMin: durationMin,
      status: status,
      phone: phone.trim(),
      notes: notes.trim(),
      version: baseVersion ?? 0,
      isPending: true,
      syncError: null,
    );
  }

  Future<void> deleteAppointment(CalendarAppointment appointment) async {
    final db = await database;
    await db.transaction((txn) async {
      if (appointment.serverId == null) {
        await txn.delete(
          'appointments_cache',
          where: 'local_id=?',
          whereArgs: [appointment.localId],
        );
        await txn.delete(
          'pending_changes',
          where: 'entity_type=? AND local_id=?',
          whereArgs: ['appointments', appointment.localId],
        );
        return;
      }
      await txn.update(
        'appointments_cache',
        {'deleted_at': DateTime.now().toUtc().toIso8601String()},
        where: 'local_id=?',
        whereArgs: [appointment.localId],
      );
      await _putPending(
        txn,
        entityType: 'appointments',
        localId: appointment.localId,
        serverId: appointment.serverId,
        action: 'delete',
        mutationId: _uuid.v4(),
        baseVersion: appointment.version,
        data: {'version': appointment.version},
      );
    });
  }

  Future<CalendarBreak> saveBreak({
    required String? localId,
    required int? serverId,
    required int masterId,
    required String date,
    required String startTime,
    required String endTime,
    required String label,
    required int? baseVersion,
  }) async {
    final db = await database;
    final key = localId ?? _uuid.v4();
    final mutationId = _uuid.v4();
    await db.transaction((txn) async {
      await txn.insert(
        'breaks_cache',
        {
          'local_id': key,
          'server_id': serverId,
          'uuid': key,
          'master_id': masterId,
          'break_date': date,
          'start_time': startTime,
          'end_time': endTime,
          'label': label.trim(),
          'version': baseVersion ?? 0,
          'deleted_at': null,
        },
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
      final previous = await txn.query(
        'pending_changes',
        columns: ['action'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['breaks', key],
        limit: 1,
      );
      final action = serverId == null ||
              (previous.isNotEmpty && previous.first['action'] == 'create')
          ? 'create'
          : 'update';
      await _putPending(
        txn,
        entityType: 'breaks',
        localId: key,
        serverId: serverId,
        action: action,
        mutationId: mutationId,
        baseVersion: baseVersion,
        data: {
          'uuid': key,
          'master_id': masterId,
          'break_date': date,
          'start_time': startTime,
          'end_time': endTime,
          'label': label.trim(),
          'version': baseVersion,
        },
      );
    });
    return CalendarBreak(
      localId: key,
      serverId: serverId,
      masterId: masterId,
      date: date,
      startTime: startTime,
      endTime: endTime,
      label: label.trim(),
      version: baseVersion ?? 0,
      isPending: true,
    );
  }

  Future<void> deleteBreak(CalendarBreak item) async {
    final db = await database;
    await db.transaction((txn) async {
      if (item.serverId == null) {
        await txn.delete('breaks_cache',
            where: 'local_id=?', whereArgs: [item.localId]);
        await txn.delete(
          'pending_changes',
          where: 'entity_type=? AND local_id=?',
          whereArgs: ['breaks', item.localId],
        );
        return;
      }
      await txn.update(
        'breaks_cache',
        {'deleted_at': DateTime.now().toUtc().toIso8601String()},
        where: 'local_id=?',
        whereArgs: [item.localId],
      );
      await _putPending(
        txn,
        entityType: 'breaks',
        localId: item.localId,
        serverId: item.serverId,
        action: 'delete',
        mutationId: _uuid.v4(),
        baseVersion: item.version,
        data: {'version': item.version},
      );
    });
  }

  Future<void> keepLocalAppointment(String localId) async {
    final db = await database;
    await db.transaction((txn) async {
      final rows = await txn.query(
        'pending_changes',
        columns: ['remote_json', 'data_json'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['appointments', localId],
        limit: 1,
      );
      if (rows.isEmpty || rows.first['remote_json'] == null) return;
      final remote = jsonDecode(rows.first['remote_json'] as String) as Map;
      final data = jsonDecode(rows.first['data_json'] as String) as Map;
      final remoteVersion = _asInt(remote['version']) ?? 0;
      data['version'] = remoteVersion;
      await txn.update(
        'pending_changes',
        {
          'base_version': remoteVersion,
          'mutation_id': _uuid.v4(),
          'data_json': jsonEncode(data),
          'error_text': null,
          'remote_json': null,
        },
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['appointments', localId],
      );
      await txn.update(
        'appointments_cache',
        {'version': remoteVersion},
        where: 'local_id=?',
        whereArgs: [localId],
      );
    });
  }

  Future<void> useServerAppointment(String localId) async {
    final db = await database;
    await db.transaction((txn) async {
      final rows = await txn.query(
        'pending_changes',
        columns: ['remote_json'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['appointments', localId],
        limit: 1,
      );
      if (rows.isEmpty || rows.first['remote_json'] == null) return;
      final remote = jsonDecode(rows.first['remote_json'] as String) as Map;
      final remoteId = _asInt(remote['id']);
      if (remoteId != null) {
        final key = (remote['uuid']?.toString().trim().isNotEmpty ?? false)
            ? remote['uuid'].toString()
            : 'server:$remoteId';
        await txn.insert(
          'appointments_cache',
          _mapScheduleRow('appointments', remote, key),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
      await txn.delete(
        'pending_changes',
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['appointments', localId],
      );
    });
  }

  Future<void> keepLocalBreak(String localId) async {
    final db = await database;
    await db.transaction((txn) async {
      final rows = await txn.query(
        'pending_changes',
        columns: ['remote_json', 'data_json'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['breaks', localId],
        limit: 1,
      );
      if (rows.isEmpty || rows.first['remote_json'] == null) return;
      final remote = jsonDecode(rows.first['remote_json'] as String) as Map;
      final data = jsonDecode(rows.first['data_json'] as String) as Map;
      final remoteVersion = _asInt(remote['version']) ?? 0;
      data['version'] = remoteVersion;
      await txn.update(
        'pending_changes',
        {
          'base_version': remoteVersion,
          'mutation_id': _uuid.v4(),
          'data_json': jsonEncode(data),
          'error_text': null,
          'remote_json': null,
        },
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['breaks', localId],
      );
      await txn.update(
        'breaks_cache',
        {'version': remoteVersion},
        where: 'local_id=?',
        whereArgs: [localId],
      );
    });
  }

  Future<void> useServerBreak(String localId) async {
    final db = await database;
    await db.transaction((txn) async {
      final rows = await txn.query(
        'pending_changes',
        columns: ['remote_json'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['breaks', localId],
        limit: 1,
      );
      if (rows.isEmpty || rows.first['remote_json'] == null) return;
      final remote = jsonDecode(rows.first['remote_json'] as String) as Map;
      final remoteId = _asInt(remote['id']);
      if (remoteId != null) {
        final key = (remote['uuid']?.toString().trim().isNotEmpty ?? false)
            ? remote['uuid'].toString()
            : 'server:$remoteId';
        await txn.insert(
          'breaks_cache',
          _mapScheduleRow('breaks', remote, key),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
      await txn.delete(
        'pending_changes',
        where: 'entity_type=? AND local_id=?',
        whereArgs: ['breaks', localId],
      );
    });
  }

  Future<List<Map<String, Object?>>> pendingChanges() async {
    final db = await database;
    return db.query(
      'pending_changes',
      where: "COALESCE(error_text, '') = ''",
      orderBy: 'created_at, id',
    );
  }

  Future<int> pendingCount() async {
    final db = await database;
    final rows =
        await db.rawQuery('SELECT COUNT(1) AS count FROM pending_changes');
    return (rows.first['count'] as int?) ?? 0;
  }

  Future<int> failedCount() async {
    final db = await database;
    final rows = await db.rawQuery(
      "SELECT COUNT(1) AS count FROM pending_changes WHERE COALESCE(error_text, '') <> ''",
    );
    return (rows.first['count'] as int?) ?? 0;
  }

  /// Applies push acknowledgements and retains failed items with their reason.
  Future<void> applyPushResult(Map<String, dynamic> result) async {
    final mappings = result['mappings'] as Map? ?? const {};
    final errors = result['errors'] as List? ?? const [];
    final db = await database;
    await db.transaction((txn) async {
      for (final error in errors.whereType<Map>()) {
        final rawType = error['type']?.toString() ?? '';
        final entityType = rawType == 'appointment'
            ? 'appointments'
            : rawType == 'break'
                ? 'breaks'
                : rawType;
        final type = _tableForType(entityType);
        final localId = error['local_id']?.toString();
        if (type == null || localId == null) continue;
        await txn.update(
          'pending_changes',
          {
            'error_text': error['detail']?.toString() ?? 'Помилка синхронізації'
          },
          where: 'entity_type=? AND local_id=?',
          whereArgs: [entityType, localId],
        );
      }
      for (final entry in mappings.entries) {
        final entityType = entry.key.toString();
        final table = _tableForType(entityType);
        if (table == null || entry.value is! List) continue;
        for (final mapping in (entry.value as List).whereType<Map>()) {
          final localId = mapping['local_id']?.toString();
          if (localId == null) continue;
          final serverId = _asInt(mapping['server_id']);
          final serverVersion = _asInt(mapping['server_version']);
          if (serverId != null) {
            await txn.update(
              '${table}_cache',
              {
                'server_id': serverId,
                if (serverVersion != null) 'version': serverVersion
              },
              where: 'local_id=?',
              whereArgs: [localId],
            );
          }
          await txn.delete(
            'pending_changes',
            where: 'entity_type=? AND local_id=?',
            whereArgs: [entityType, localId],
          );
        }
      }
    });
  }

  Future<void> setMeta(String key, String value) async {
    final db = await database;
    await db.insert(
      'sync_meta',
      {'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<String?> accountScope() => getMeta('account_scope');

  /// Keeps account data isolated and refuses to discard unsent edits on switch.
  Future<void> setAccountProfile(String role, int? masterId) async {
    final scope = role == 'master' ? 'master:${masterId ?? 0}' : 'admin';
    final db = await database;
    await db.transaction((txn) async {
      final rows = await txn.query(
        'sync_meta',
        columns: ['value'],
        where: 'key=?',
        whereArgs: ['account_scope'],
        limit: 1,
      );
      final previous = rows.isEmpty ? null : rows.first['value'] as String?;
      if (previous != null && previous != scope) {
        final pending = await txn.rawQuery(
          'SELECT COUNT(1) AS count FROM pending_changes',
        );
        if ((pending.first['count'] as int? ?? 0) > 0) {
          throw StateError(
            'Спочатку синхронізуйте зміни профілю $previous або увійдіть у нього знову.',
          );
        }
        for (final table in [
          'appointments_cache',
          'breaks_cache',
          'clients_cache',
          'services_cache',
          'masters_cache',
        ]) {
          await txn.delete(table);
        }
        await txn
            .delete('sync_meta', where: 'key=?', whereArgs: ['last_sync_at']);
      }
      await _putMeta(txn, 'account_scope', scope);
      await _putMeta(txn, 'account_role', role);
      await _putMeta(txn, 'account_master_id', masterId?.toString() ?? '');
    });
  }

  Future<Map<String, Object?>> accountProfile() async {
    final role = await getMeta('account_role');
    final master = await getMeta('account_master_id');
    return {
      'role': role ?? '',
      'master_id': _asInt(master),
    };
  }

  Future<String?> getMeta(String key) async {
    final db = await database;
    final rows = await db.query(
      'sync_meta',
      columns: ['value'],
      where: 'key=?',
      whereArgs: [key],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first['value'] as String?;
  }

  Future<DateTime?> loadLastSyncAt() async {
    final value = await getMeta('last_sync_at');
    if (value == null || value.isEmpty) return null;
    return DateTime.tryParse(value);
  }

  Future<int> databaseSizeBytes() async {
    await database;
    final dbPath = _databasePath;
    if (dbPath == null) return 0;
    final file = File(dbPath);
    if (!await file.exists()) return 0;
    return file.length();
  }

  Future<void> close() async {
    await _database?.close();
    _database = null;
  }

  Future<int> countAppointments() => _countRows('appointments_cache');
  Future<int> countClients() => _countRows('clients_cache');
  Future<int> countBreaks() => _countRows('breaks_cache');

  Future<int> _countRows(String table) async {
    final db = await database;
    final rows = await db.rawQuery(
      'SELECT COUNT(1) as count FROM $table WHERE deleted_at IS NULL',
    );
    return (rows.first['count'] as int?) ?? 0;
  }

  Future<void> _createSchema(Database db, int version) async {
    await _createReferenceTables(db);
    await _createScheduleTables(db);
    await _createOutbox(db);
    await _createMeta(db);
  }

  Future<void> _upgradeSchema(
      Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 2) {
      await db.execute(
          'ALTER TABLE services_cache ADD COLUMN duration_min INTEGER');
      await db
          .execute('ALTER TABLE services_cache ADD COLUMN price_cents INTEGER');
      await db.execute(
          'ALTER TABLE appointments_cache RENAME TO appointments_cache_v1');
      await db.execute('ALTER TABLE breaks_cache RENAME TO breaks_cache_v1');
      await _createScheduleTables(db);
      await db.execute('''
        INSERT INTO appointments_cache (
          local_id, server_id, uuid, master_id, client_id, client_name, phone,
          service, service_ids, appt_date, start_time, duration_min, notes,
          status, created_at, updated_at, deleted_at, version
        )
        SELECT COALESCE(NULLIF(uuid, ''), 'server:' || server_id), server_id, uuid,
          master_id, client_id, client_name, phone, service, '[]', appt_date,
          start_time, duration_min, notes, status, created_at, updated_at,
          deleted_at, COALESCE(version, 0)
        FROM appointments_cache_v1
      ''');
      await db.execute('''
        INSERT INTO breaks_cache (
          local_id, server_id, uuid, master_id, break_date, start_time,
          end_time, label, updated_at, deleted_at, version
        )
        SELECT COALESCE(NULLIF(uuid, ''), 'server:' || server_id), server_id,
          uuid, master_id, break_date, start_time, end_time, label, updated_at,
          deleted_at, COALESCE(version, 0)
        FROM breaks_cache_v1
      ''');
      await db.execute('DROP TABLE appointments_cache_v1');
      await db.execute('DROP TABLE breaks_cache_v1');
      await _createOutbox(db);
    }
  }

  Future<void> _createReferenceTables(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS masters_cache (
        server_id INTEGER PRIMARY KEY, uuid TEXT, name TEXT, color TEXT,
        initials TEXT, updated_at TEXT, deleted_at TEXT, version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS services_cache (
        server_id INTEGER PRIMARY KEY, uuid TEXT, name TEXT, sort_order INTEGER,
        duration_min INTEGER, price_cents INTEGER, updated_at TEXT,
        deleted_at TEXT, version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS clients_cache (
        server_id INTEGER PRIMARY KEY, uuid TEXT, first_name TEXT,
        last_name TEXT, phone TEXT, birthday TEXT, telegram_chat_id TEXT,
        notes TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT,
        version INTEGER
      )
    ''');
  }

  Future<void> _createScheduleTables(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS appointments_cache (
        local_id TEXT PRIMARY KEY, server_id INTEGER UNIQUE, uuid TEXT,
        master_id INTEGER NOT NULL, client_id INTEGER, client_name TEXT NOT NULL,
        phone TEXT DEFAULT '', service TEXT NOT NULL, service_ids TEXT DEFAULT '[]',
        appt_date TEXT NOT NULL, start_time TEXT NOT NULL,
        duration_min INTEGER NOT NULL DEFAULT 60, notes TEXT DEFAULT '',
        status TEXT DEFAULT 'scheduled', created_at TEXT, updated_at TEXT,
        deleted_at TEXT, version INTEGER DEFAULT 0
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS breaks_cache (
        local_id TEXT PRIMARY KEY, server_id INTEGER UNIQUE, uuid TEXT,
        master_id INTEGER NOT NULL, break_date TEXT NOT NULL,
        start_time TEXT NOT NULL, end_time TEXT NOT NULL, label TEXT,
        updated_at TEXT, deleted_at TEXT, version INTEGER DEFAULT 0
      )
    ''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments_cache(appt_date, start_time)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_breaks_date ON breaks_cache(break_date, start_time)',
    );
  }

  Future<void> _createOutbox(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS pending_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        local_id TEXT NOT NULL,
        server_id INTEGER,
        action TEXT NOT NULL,
        mutation_id TEXT NOT NULL,
        base_version INTEGER,
        data_json TEXT NOT NULL,
        error_text TEXT,
        remote_json TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(entity_type, local_id)
      )
    ''');
  }

  Future<void> _createMeta(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT)
    ''');
  }

  Future<void> _putMeta(DatabaseExecutor db, String key, String value) async {
    await db.insert(
      'sync_meta',
      {'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> _upsertReferenceRows(
    DatabaseExecutor db,
    String table,
    dynamic input,
  ) async {
    for (final row in (input as List? ?? const []).whereType<Map>()) {
      final mapped = _mapReferenceRow(table, row);
      if (mapped['server_id'] == null) continue;
      await db.insert(table, mapped,
          conflictAlgorithm: ConflictAlgorithm.replace);
    }
  }

  Future<void> _applyRemoteRows(
    DatabaseExecutor db,
    String type,
    dynamic input,
  ) async {
    final table = _tableForType(type);
    if (table == null) return;
    for (final row in (input as List? ?? const []).whereType<Map>()) {
      final serverId = _asInt(row['id']);
      if (serverId == null) continue;
      final localId = (row['uuid']?.toString().trim().isNotEmpty ?? false)
          ? row['uuid'].toString()
          : 'server:$serverId';
      final pending = await db.query(
        'pending_changes',
        columns: ['id', 'mutation_id', 'base_version'],
        where: 'entity_type=? AND local_id=?',
        whereArgs: [type, localId],
        limit: 1,
      );
      if (pending.isNotEmpty) {
        final remoteVersion = _asInt(row['version']) ?? 0;
        final baseVersion = _asInt(pending.first['base_version']) ?? 0;
        final mutationId = pending.first['mutation_id']?.toString() ?? '';
        final remoteMutationId = row['last_mutation_id']?.toString() ?? '';
        if (remoteVersion != baseVersion && remoteMutationId != mutationId) {
          await db.update(
            'pending_changes',
            {
              'error_text': 'Запис змінено на іншому пристрої',
              'remote_json': jsonEncode(row),
            },
            where: 'entity_type=? AND local_id=?',
            whereArgs: [type, localId],
          );
        }
        continue;
      }
      await db.insert(
        '${table}_cache',
        _mapScheduleRow(type, row, localId),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
  }

  Map<String, Object?> _mapReferenceRow(
      String table, Map<dynamic, dynamic> row) {
    final id = _asInt(row['id']);
    switch (table) {
      case 'masters_cache':
        return {
          'server_id': id,
          'uuid': row['uuid'],
          'name': row['name'],
          'color': row['color'],
          'initials': row['initials'],
          'updated_at': row['updated_at'],
          'deleted_at': row['deleted_at'],
          'version': _asInt(row['version']),
        };
      case 'services_cache':
        return {
          'server_id': id,
          'uuid': row['uuid'],
          'name': row['name'],
          'sort_order': _asInt(row['sort_order']),
          'duration_min': _asInt(row['duration_min']),
          'price_cents': _asInt(row['price_cents']),
          'updated_at': row['updated_at'],
          'deleted_at': row['deleted_at'],
          'version': _asInt(row['version']),
        };
      case 'clients_cache':
        return {
          'server_id': id,
          'uuid': row['uuid'],
          'first_name': row['first_name'],
          'last_name': row['last_name'],
          'phone': row['phone'],
          'birthday': row['birthday'],
          'telegram_chat_id': row['telegram_chat_id'],
          'notes': row['notes'],
          'created_at': row['created_at'],
          'updated_at': row['updated_at'],
          'deleted_at': row['deleted_at'],
          'version': _asInt(row['version']),
        };
      default:
        return {'server_id': id};
    }
  }

  Map<String, Object?> _mapScheduleRow(
    String type,
    Map<dynamic, dynamic> row,
    String localId,
  ) {
    final id = _asInt(row['id']);
    if (type == 'appointments') {
      final serviceIds = row['service_ids'] as List? ??
          (row['services'] as List? ?? const [])
              .whereType<Map>()
              .map((service) => service['service_id'] ?? service['id'])
              .where((value) => value != null)
              .toList();
      return {
        'local_id': localId,
        'server_id': id,
        'uuid': row['uuid'],
        'master_id': _asInt(row['master_id']),
        'client_id': _asInt(row['client_id']),
        'client_name': row['client_name'] ?? '',
        'phone': row['phone'] ?? '',
        'service': row['service'] ?? '',
        'service_ids':
            jsonEncode(serviceIds.map(_asInt).whereType<int>().toList()),
        'appt_date': row['appt_date'],
        'start_time': row['start_time'],
        'duration_min': _asInt(row['duration_min']) ?? 60,
        'notes': row['notes'] ?? '',
        'status': row['status'] ?? 'scheduled',
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'deleted_at': row['deleted_at'],
        'version': _asInt(row['version']) ?? 0,
      };
    }
    return {
      'local_id': localId,
      'server_id': id,
      'uuid': row['uuid'],
      'master_id': _asInt(row['master_id']),
      'break_date': row['break_date'],
      'start_time': row['start_time'],
      'end_time': row['end_time'],
      'label': row['label'] ?? 'Зайнято',
      'updated_at': row['updated_at'],
      'deleted_at': row['deleted_at'],
      'version': _asInt(row['version']) ?? 0,
    };
  }

  Future<void> _putPending(
    DatabaseExecutor txn, {
    required String entityType,
    required String localId,
    required int? serverId,
    required String action,
    required String mutationId,
    required int? baseVersion,
    required Map<String, Object?> data,
  }) async {
    await txn.insert(
      'pending_changes',
      {
        'entity_type': entityType,
        'local_id': localId,
        'server_id': serverId,
        'action': action,
        'mutation_id': mutationId,
        'base_version': baseVersion,
        'data_json': jsonEncode(data),
        'error_text': null,
        'remote_json': null,
        'created_at': DateTime.now().toUtc().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  String? _tableForType(String type) {
    switch (type) {
      case 'appointments':
        return 'appointments';
      case 'breaks':
        return 'breaks';
      default:
        return null;
    }
  }

  int? _asInt(Object? value) {
    if (value == null || value == '') return null;
    if (value is int) return value;
    return int.tryParse(value.toString());
  }
}
