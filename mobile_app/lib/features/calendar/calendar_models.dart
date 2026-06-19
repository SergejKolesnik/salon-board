class CalendarAppointment {
  CalendarAppointment({
    required this.serverId,
    required this.masterId,
    required this.clientName,
    required this.service,
    required this.date,
    required this.startTime,
    required this.durationMin,
    required this.status,
    this.phone = '',
    this.notes = '',
  });

  final int serverId;
  final int masterId;
  final String clientName;
  final String service;
  final String date;
  final String startTime;
  final int durationMin;
  final String status;
  final String phone;
  final String notes;

  factory CalendarAppointment.fromDb(Map<String, Object?> row) {
    return CalendarAppointment(
      serverId: row['server_id'] as int,
      masterId: row['master_id'] as int,
      clientName: (row['client_name'] as String?) ?? '',
      service: (row['service'] as String?) ?? '',
      date: (row['appt_date'] as String?) ?? '',
      startTime: (row['start_time'] as String?) ?? '',
      durationMin: (row['duration_min'] as int?) ?? 60,
      status: (row['status'] as String?) ?? 'scheduled',
      phone: (row['phone'] as String?) ?? '',
      notes: (row['notes'] as String?) ?? '',
    );
  }
}

class CalendarBreak {
  CalendarBreak({
    required this.serverId,
    required this.masterId,
    required this.date,
    required this.startTime,
    required this.endTime,
    required this.label,
  });

  final int serverId;
  final int masterId;
  final String date;
  final String startTime;
  final String endTime;
  final String label;

  factory CalendarBreak.fromDb(Map<String, Object?> row) {
    return CalendarBreak(
      serverId: row['server_id'] as int,
      masterId: row['master_id'] as int,
      date: (row['break_date'] as String?) ?? '',
      startTime: (row['start_time'] as String?) ?? '',
      endTime: (row['end_time'] as String?) ?? '',
      label: (row['label'] as String?) ?? 'Зайнято',
    );
  }
}

class CachedSchedule {
  CachedSchedule({required this.appointments, required this.breaks});

  final List<CalendarAppointment> appointments;
  final List<CalendarBreak> breaks;
}
