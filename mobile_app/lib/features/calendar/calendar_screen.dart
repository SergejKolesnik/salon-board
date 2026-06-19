import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/sync/sync_service.dart';
import '../../core/sync/sync_status.dart';
import 'calendar_models.dart';

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({required this.syncService, super.key});

  final SyncService syncService;

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  late DateTime _weekStart;
  CachedSchedule _schedule = CachedSchedule(appointments: [], breaks: []);
  bool _isLoadingCache = true;

  @override
  void initState() {
    super.initState();
    _weekStart = _startOfDay(DateTime.now());
    widget.syncService.status.addListener(_reloadCache);
    _reloadCache();
  }

  @override
  void dispose() {
    widget.syncService.status.removeListener(_reloadCache);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final weekEnd = _weekStart.add(const Duration(days: 6));
    return Scaffold(
      appBar: AppBar(
        title: Text(
          '${_formatDate(_weekStart)} - ${_formatDate(weekEnd)}',
        ),
        actions: [
          IconButton(
            onPressed: () {
              setState(
                () => _weekStart = _weekStart.subtract(const Duration(days: 7)),
              );
              _reloadCache();
            },
            icon: const Icon(Icons.chevron_left),
          ),
          IconButton(
            onPressed: () {
              setState(() => _weekStart = _startOfDay(DateTime.now()));
              _reloadCache();
            },
            icon: const Icon(Icons.today),
          ),
          IconButton(
            onPressed: () {
              setState(
                () => _weekStart = _weekStart.add(const Duration(days: 7)),
              );
              _reloadCache();
            },
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
      body: Column(
        children: [
          ValueListenableBuilder<SyncStatus>(
            valueListenable: widget.syncService.status,
            builder: (context, status, _) => _SyncBanner(
              status: status,
              onSync: widget.syncService.syncNow,
            ),
          ),
          Expanded(
            child: _isLoadingCache
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: widget.syncService.syncNow,
                    child: ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: 7,
                      itemBuilder: (context, index) {
                        final day = _weekStart.add(Duration(days: index));
                        final iso = DateFormat('yyyy-MM-dd').format(day);
                        return _DaySection(
                          date: day,
                          appointments: _schedule.appointments
                              .where((item) => item.date == iso)
                              .toList(),
                          breaks: _schedule.breaks
                              .where((item) => item.date == iso)
                              .toList(),
                        );
                      },
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Future<void> _reloadCache() async {
    final schedule = await widget.syncService.database.loadSchedule(
      _weekStart,
      _weekStart.add(const Duration(days: 6)),
    );
    if (!mounted) return;
    setState(() {
      _schedule = schedule;
      _isLoadingCache = false;
    });
  }

  DateTime _startOfDay(DateTime value) {
    return DateTime(value.year, value.month, value.day);
  }

  String _formatDate(DateTime value) {
    return DateFormat('dd.MM').format(value);
  }
}

class _SyncBanner extends StatelessWidget {
  const _SyncBanner({required this.status, required this.onSync});

  final SyncStatus status;
  final Future<void> Function() onSync;

  @override
  Widget build(BuildContext context) {
    final color = status.isOnline ? Colors.greenAccent : Colors.orangeAccent;
    final lastSync = status.lastSyncAt == null
        ? 'ще не було'
        : DateFormat('dd.MM HH:mm').format(status.lastSyncAt!.toLocal());
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            Icon(Icons.circle, size: 10, color: color),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '${status.isOnline ? 'Online' : 'Offline'} | Last sync: $lastSync',
              ),
            ),
            if (status.isSyncing)
              const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              TextButton(onPressed: onSync, child: const Text('Sync')),
          ],
        ),
      ),
    );
  }
}

class _DaySection extends StatelessWidget {
  const _DaySection({
    required this.date,
    required this.appointments,
    required this.breaks,
  });

  final DateTime date;
  final List<CalendarAppointment> appointments;
  final List<CalendarBreak> breaks;

  @override
  Widget build(BuildContext context) {
    final events = <Widget>[
      ...appointments.map((item) => _AppointmentTile(item: item)),
      ...breaks.map((item) => _BreakTile(item: item)),
    ];
    events.sort((a, b) => _eventTime(a).compareTo(_eventTime(b)));

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              DateFormat('EEE, dd.MM').format(date),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            if (events.isEmpty)
              Text(
                'Немає подій',
                style: TextStyle(color: Theme.of(context).colorScheme.outline),
              )
            else
              ...events,
          ],
        ),
      ),
    );
  }

  String _eventTime(Widget widget) {
    if (widget is _AppointmentTile) return widget.item.startTime;
    if (widget is _BreakTile) return widget.item.startTime;
    return '';
  }
}

class _AppointmentTile extends StatelessWidget {
  const _AppointmentTile({required this.item});

  final CalendarAppointment item;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.event_available),
      title: Text('${item.startTime} | ${item.clientName}'),
      subtitle: Text('${item.service} | ${item.durationMin} хв | ${item.status}'),
    );
  }
}

class _BreakTile extends StatelessWidget {
  const _BreakTile({required this.item});

  final CalendarBreak item;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.block),
      title: Text('${item.startTime}-${item.endTime} | ${item.label}'),
      subtitle: const Text('Зайнятий час'),
    );
  }
}
