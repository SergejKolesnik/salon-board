import '../../core/sync/sync_service.dart';
import '../calendar/calendar_models.dart';

/// Connects the established PWA calendar to the native SQLite outbox.
class PwaBridge {
  const PwaBridge(this.sync);

  final SyncService sync;

  Future<Object?> handle(String action, Map<String, dynamic> data) async {
    switch (action) {
      case 'me':
        final profile = await sync.accountProfile();
        final masters = await sync.database.loadMasters();
        final id = _int(profile['master_id']);
        final master = masters.where((row) => _int(row['server_id']) == id);
        return {'role': 'master', 'master_id': id, 'name': master.isEmpty ? 'Майстер' : master.first['name']};
      case 'masters':
        return (await sync.database.loadMasters()).map((row) => {
          ...row,
          'id': row['server_id'],
        }).toList();
      case 'services':
        return (await sync.database.loadServices()).map((item) => {
          'id': item.id,
          'name': item.name,
          'duration_min': item.durationMin,
          'price_cents': item.priceCents,
        }).toList();
      case 'clients':
        final query = data['query']?.toString() ?? '';
        return (await sync.database.searchClients(query)).map((item) => {
          'id': item.id,
          'first_name': item.name,
          'last_name': '',
          'phone': item.phone,
        }).toList();
      case 'schedule':
        final start = DateTime.parse(data['from'] as String);
        final end = DateTime.parse(data['to'] as String);
        final schedule = await sync.database.loadSchedule(start, end);
        final masterId = _int(data['master_id']);
        return {
          'appointments': schedule.appointments.where((a) => a.masterId == masterId).map(_appointmentJson).toList(),
          'breaks': schedule.breaks.where((b) => b.masterId == masterId).map(_breakJson).toList(),
        };
      case 'saveAppointment':
        final body = Map<String, dynamic>.from(data['body'] as Map);
        final old = data['existing'] is Map ? Map<String, dynamic>.from(data['existing'] as Map) : null;
        final item = await sync.saveAppointment(
          existing: old == null ? null : _appointmentFromJson(old),
          masterId: _int(body['master_id'])!,
          clientName: body['client_name']?.toString() ?? '',
          phone: body['phone']?.toString() ?? '',
          service: body['service']?.toString() ?? '',
          serviceIds: (body['service_ids'] as List? ?? []).map(_int).whereType<int>().toList(),
          clientId: _int(body['client_id']),
          date: body['appt_date'] as String,
          startTime: body['start_time'] as String,
          durationMin: _int(body['duration_min']) ?? 60,
          notes: body['notes']?.toString() ?? '',
          appointmentStatus: body['status']?.toString() ?? 'scheduled',
        );
        return _appointmentJson(item);
      case 'deleteAppointment':
        await sync.deleteAppointment(_appointmentFromJson(Map<String, dynamic>.from(data['existing'] as Map)));
        return {'ok': true};
      case 'saveBreak':
        final body = Map<String, dynamic>.from(data['body'] as Map);
        final old = data['existing'] is Map ? Map<String, dynamic>.from(data['existing'] as Map) : null;
        final item = await sync.saveBreak(
          existing: old == null ? null : _breakFromJson(old),
          masterId: _int(body['master_id'])!,
          date: body['break_date'] as String,
          startTime: body['start_time'] as String,
          endTime: body['end_time'] as String,
          label: body['label']?.toString() ?? 'Зайнято',
        );
        return _breakJson(item);
      case 'deleteBreak':
        await sync.deleteBreak(_breakFromJson(Map<String, dynamic>.from(data['existing'] as Map)));
        return {'ok': true};
      case 'syncStatus':
        final state = sync.status.value;
        return {
          'isOnline': state.isOnline,
          'isSyncing': state.isSyncing,
          'pendingCount': state.pendingCount,
          'failedCount': state.failedCount,
          'lastSyncAt': state.lastSyncAt?.toIso8601String(),
          'error': state.error,
        };
      case 'syncNow':
        await sync.syncNow();
        return {'ok': true};
      default:
        throw ArgumentError('Невідома локальна дія');
    }
  }

  static int? _int(Object? value) => value == null ? null : int.tryParse(value.toString());
  static String _localId(Map<String, dynamic> row) =>
      row['local_id']?.toString() ?? row['uuid']?.toString() ?? 'server:${row['id']}';
  static int? _serverId(Map<String, dynamic> row) =>
      _int(row['server_id']) ?? _int(row['id']);

  static CalendarAppointment _appointmentFromJson(Map<String, dynamic> row) => CalendarAppointment(
    localId: _localId(row), serverId: _serverId(row),
    masterId: _int(row['master_id']) ?? 0, clientId: _int(row['client_id']),
    clientName: row['client_name']?.toString() ?? '', phone: row['phone']?.toString() ?? '',
    service: row['service']?.toString() ?? '',
    serviceIds: (row['service_ids'] as List? ?? []).map(_int).whereType<int>().toList(),
    date: row['appt_date']?.toString() ?? '', startTime: row['start_time']?.toString() ?? '',
    durationMin: _int(row['duration_min']) ?? 60, notes: row['notes']?.toString() ?? '',
    status: row['status']?.toString() ?? 'scheduled', version: _int(row['version']) ?? 0,
    isPending: row['is_pending'] == true,
  );

  static CalendarBreak _breakFromJson(Map<String, dynamic> row) => CalendarBreak(
    localId: _localId(row), serverId: _serverId(row), masterId: _int(row['master_id']) ?? 0,
    date: row['break_date']?.toString() ?? '', startTime: row['start_time']?.toString() ?? '',
    endTime: row['end_time']?.toString() ?? '', label: row['label']?.toString() ?? 'Зайнято',
    version: _int(row['version']) ?? 0, isPending: row['is_pending'] == true,
  );

  static Map<String, Object?> _appointmentJson(CalendarAppointment a) => {
    'id': a.serverId ?? 'local:${a.localId}', 'local_id': a.localId,
    'server_id': a.serverId, 'uuid': a.localId, 'master_id': a.masterId,
    'client_id': a.clientId, 'client_name': a.clientName, 'phone': a.phone,
    'service': a.service, 'service_ids': a.serviceIds, 'appt_date': a.date,
    'start_time': a.startTime, 'duration_min': a.durationMin, 'notes': a.notes,
    'status': a.status, 'version': a.version, 'is_pending': a.isPending,
    'sync_error': a.syncError,
  };

  static Map<String, Object?> _breakJson(CalendarBreak b) => {
    'id': b.serverId ?? 'local:${b.localId}', 'local_id': b.localId,
    'server_id': b.serverId, 'uuid': b.localId, 'master_id': b.masterId,
    'break_date': b.date, 'start_time': b.startTime, 'end_time': b.endTime,
    'label': b.label, 'version': b.version, 'is_pending': b.isPending,
    'sync_error': b.syncError,
  };
}
