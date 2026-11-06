import 'dart:convert';

class CalendarAppointment {
  CalendarAppointment({
    required this.localId,
    required this.serverId,
    required this.masterId,
    required this.clientName,
    required this.service,
    required this.serviceIds,
    required this.date,
    required this.startTime,
    required this.durationMin,
    required this.status,
    required this.version,
    required this.isPending,
    this.clientId,
    this.phone = '',
    this.notes = '',
    this.syncError,
    this.hasServerConflict = false,
  });

  final String localId;
  final int? serverId;
  final int masterId;
  final int? clientId;
  final String clientName;
  final String service;
  final List<int> serviceIds;
  final String date;
  final String startTime;
  final int durationMin;
  final String status;
  final int version;
  final String phone;
  final String notes;
  final String? syncError;
  final bool hasServerConflict;
  final bool isPending;

  factory CalendarAppointment.fromDb(Map<String, Object?> row) {
    final rawServiceIds = row['service_ids'] as String? ?? '[]';
    final decoded = jsonDecode(rawServiceIds);
    return CalendarAppointment(
      localId: (row['local_id'] as String?) ?? 'server:${row['server_id']}',
      serverId: _asInt(row['server_id']),
      masterId: _asInt(row['master_id']) ?? 0,
      clientId: _asInt(row['client_id']),
      clientName: (row['client_name'] as String?) ?? '',
      service: (row['service'] as String?) ?? '',
      serviceIds: decoded is List ? decoded.map(_asInt).whereType<int>().toList() : const [],
      date: (row['appt_date'] as String?) ?? '',
      startTime: (row['start_time'] as String?) ?? '',
      durationMin: _asInt(row['duration_min']) ?? 60,
      status: (row['status'] as String?) ?? 'scheduled',
      version: _asInt(row['version']) ?? 0,
      isPending: _asInt(row['is_pending']) == 1,
      phone: (row['phone'] as String?) ?? '',
      notes: (row['notes'] as String?) ?? '',
      syncError: (row['sync_error'] as String?)?.isEmpty == true
          ? null
          : row['sync_error'] as String?,
      hasServerConflict: row['remote_json'] != null,
    );
  }
}

class CalendarBreak {
  CalendarBreak({
    required this.localId,
    required this.serverId,
    required this.masterId,
    required this.date,
    required this.startTime,
    required this.endTime,
    required this.label,
    required this.version,
    required this.isPending,
    this.syncError,
    this.hasServerConflict = false,
  });

  final String localId;
  final int? serverId;
  final int masterId;
  final String date;
  final String startTime;
  final String endTime;
  final String label;
  final int version;
  final String? syncError;
  final bool isPending;
  final bool hasServerConflict;

  factory CalendarBreak.fromDb(Map<String, Object?> row) {
    return CalendarBreak(
      localId: (row['local_id'] as String?) ?? 'server:${row['server_id']}',
      serverId: _asInt(row['server_id']),
      masterId: _asInt(row['master_id']) ?? 0,
      date: (row['break_date'] as String?) ?? '',
      startTime: (row['start_time'] as String?) ?? '',
      endTime: (row['end_time'] as String?) ?? '',
      label: (row['label'] as String?) ?? 'Зайнято',
      version: _asInt(row['version']) ?? 0,
      isPending: _asInt(row['is_pending']) == 1,
      syncError: (row['sync_error'] as String?)?.isEmpty == true
          ? null
          : row['sync_error'] as String?,
      hasServerConflict: row['remote_json'] != null,
    );
  }
}

class ServiceOption {
  const ServiceOption({
    required this.id,
    required this.name,
    required this.durationMin,
    this.priceCents,
  });

  final int id;
  final String name;
  final int durationMin;
  final int? priceCents;

  factory ServiceOption.fromDb(Map<String, Object?> row) => ServiceOption(
        id: _asInt(row['server_id']) ?? 0,
        name: row['name']?.toString() ?? '',
        durationMin: _asInt(row['duration_min']) ?? 60,
        priceCents: _asInt(row['price_cents']),
      );
}

class ClientOption {
  const ClientOption({
    required this.id,
    required this.name,
    required this.phone,
  });

  final int id;
  final String name;
  final String phone;

  factory ClientOption.fromDb(Map<String, Object?> row) => ClientOption(
        id: _asInt(row['server_id']) ?? 0,
        name: [row['first_name'], row['last_name']]
            .where((part) => part != null && part.toString().trim().isNotEmpty)
            .map((part) => part.toString().trim())
            .join(' '),
        phone: row['phone']?.toString() ?? '',
      );

  @override
  String toString() => phone.isEmpty ? name : '$name · $phone';
}

class CachedSchedule {
  CachedSchedule({required this.appointments, required this.breaks});

  final List<CalendarAppointment> appointments;
  final List<CalendarBreak> breaks;
}

int? _asInt(Object? value) {
  if (value == null || value == '') return null;
  if (value is int) return value;
  return int.tryParse(value.toString());
}
