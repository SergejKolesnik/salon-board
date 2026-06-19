import 'package:intl/intl.dart';
import 'package:path/path.dart' as path;
import 'package:sqflite/sqflite.dart';

import '../../features/calendar/calendar_models.dart';

class LocalDatabase {
  Database? _database;

  Future<Database> get database async {
    final existing = _database;
    if (existing != null) return existing;

    final dbPath = await getDatabasesPath();
    final db = await openDatabase(
      path.join(dbPath, 'salon_board_mobile.db'),
      version: 1,
      onCreate: _createSchema,
    );
    _database = db;
    return db;
  }

  Future<void> saveBootstrap(Map<String, dynamic> payload) async {
    final db = await database;
    final batch = db.batch();

    _upsertAll(batch, 'masters_cache', payload['masters'] as List? ?? const []);
    _upsertAll(batch, 'services_cache', payload['services'] as List? ?? const []);
    _upsertAll(batch, 'clients_cache', payload['clients'] as List? ?? const []);
    _upsertAll(
      batch,
      'appointments_cache',
      payload['appointments'] as List? ?? const [],
    );
    _upsertAll(batch, 'breaks_cache', payload['breaks'] as List? ?? const []);

    batch.insert(
      'sync_meta',
      {'key': 'last_sync_at', 'value': payload['server_time']?.toString() ?? ''},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
    await batch.commit(noResult: true);
  }

  Future<CachedSchedule> loadSchedule(DateTime start, DateTime end) async {
    final db = await database;
    final fmt = DateFormat('yyyy-MM-dd');
    final startIso = fmt.format(start);
    final endIso = fmt.format(end);

    final appointmentRows = await db.query(
      'appointments_cache',
      where: 'appt_date >= ? AND appt_date <= ? AND deleted_at IS NULL',
      whereArgs: [startIso, endIso],
      orderBy: 'appt_date, start_time, server_id',
    );
    final breakRows = await db.query(
      'breaks_cache',
      where: 'break_date >= ? AND break_date <= ? AND deleted_at IS NULL',
      whereArgs: [startIso, endIso],
      orderBy: 'break_date, start_time, server_id',
    );

    return CachedSchedule(
      appointments: appointmentRows.map(CalendarAppointment.fromDb).toList(),
      breaks: breakRows.map(CalendarBreak.fromDb).toList(),
    );
  }

  Future<DateTime?> loadLastSyncAt() async {
    final db = await database;
    final rows = await db.query(
      'sync_meta',
      where: 'key = ?',
      whereArgs: ['last_sync_at'],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    final value = rows.first['value'] as String?;
    if (value == null || value.isEmpty) return null;
    return DateTime.tryParse(value);
  }

  Future<void> _createSchema(Database db, int version) async {
    await db.execute('''
      CREATE TABLE masters_cache (
        server_id INTEGER PRIMARY KEY,
        uuid TEXT,
        name TEXT,
        color TEXT,
        initials TEXT,
        updated_at TEXT,
        deleted_at TEXT,
        version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE services_cache (
        server_id INTEGER PRIMARY KEY,
        uuid TEXT,
        name TEXT,
        sort_order INTEGER,
        updated_at TEXT,
        deleted_at TEXT,
        version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE clients_cache (
        server_id INTEGER PRIMARY KEY,
        uuid TEXT,
        first_name TEXT,
        last_name TEXT,
        phone TEXT,
        birthday TEXT,
        telegram_chat_id TEXT,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        deleted_at TEXT,
        version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE appointments_cache (
        server_id INTEGER PRIMARY KEY,
        uuid TEXT,
        master_id INTEGER,
        client_id INTEGER,
        client_name TEXT,
        phone TEXT,
        service TEXT,
        appt_date TEXT,
        start_time TEXT,
        duration_min INTEGER,
        notes TEXT,
        status TEXT,
        created_at TEXT,
        updated_at TEXT,
        deleted_at TEXT,
        version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE breaks_cache (
        server_id INTEGER PRIMARY KEY,
        uuid TEXT,
        master_id INTEGER,
        break_date TEXT,
        start_time TEXT,
        end_time TEXT,
        label TEXT,
        updated_at TEXT,
        deleted_at TEXT,
        version INTEGER
      )
    ''');
    await db.execute('''
      CREATE TABLE sync_meta (
        key TEXT PRIMARY KEY,
        value TEXT
      )
    ''');
  }

  void _upsertAll(Batch batch, String table, List<dynamic> rows) {
    for (final row in rows.whereType<Map>()) {
      final mapped = _mapRow(table, row);
      if (mapped['server_id'] == null) continue;
      batch.insert(table, mapped, conflictAlgorithm: ConflictAlgorithm.replace);
    }
  }

  Map<String, Object?> _mapRow(String table, Map<dynamic, dynamic> row) {
    final serverId = _asInt(row['id']);
    switch (table) {
      case 'masters_cache':
        return {
          'server_id': serverId,
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
          'server_id': serverId,
          'uuid': row['uuid'],
          'name': row['name'],
          'sort_order': _asInt(row['sort_order']),
          'updated_at': row['updated_at'],
          'deleted_at': row['deleted_at'],
          'version': _asInt(row['version']),
        };
      case 'clients_cache':
        return {
          'server_id': serverId,
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
      case 'appointments_cache':
        return {
          'server_id': serverId,
          'uuid': row['uuid'],
          'master_id': _asInt(row['master_id']),
          'client_id': _asInt(row['client_id']),
          'client_name': row['client_name'],
          'phone': row['phone'],
          'service': row['service'],
          'appt_date': row['appt_date'],
          'start_time': row['start_time'],
          'duration_min': _asInt(row['duration_min']),
          'notes': row['notes'],
          'status': row['status'],
          'created_at': row['created_at'],
          'updated_at': row['updated_at'],
          'deleted_at': row['deleted_at'],
          'version': _asInt(row['version']),
        };
      case 'breaks_cache':
        return {
          'server_id': serverId,
          'uuid': row['uuid'],
          'master_id': _asInt(row['master_id']),
          'break_date': row['break_date'],
          'start_time': row['start_time'],
          'end_time': row['end_time'],
          'label': row['label'],
          'updated_at': row['updated_at'],
          'deleted_at': row['deleted_at'],
          'version': _asInt(row['version']),
        };
      default:
        return {'server_id': serverId};
    }
  }

  int? _asInt(Object? value) {
    if (value == null || value == '') return null;
    if (value is int) return value;
    return int.tryParse(value.toString());
  }
}
