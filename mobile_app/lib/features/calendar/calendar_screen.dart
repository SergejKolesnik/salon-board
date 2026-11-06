import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/api/api_client.dart';
import '../../core/sync/sync_service.dart';
import '../../core/sync/sync_status.dart';
import '../auth/login_screen.dart';
import '../diagnostics/sync_diagnostics_screen.dart';
import 'appointment_editor.dart';
import 'break_editor.dart';
import 'calendar_models.dart';

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({
    required this.syncService,
    required this.apiClient,
    super.key,
  });

  final SyncService syncService;
  final ApiClient apiClient;

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen>
    with WidgetsBindingObserver {
  late DateTime _weekStart;
  CachedSchedule _schedule = CachedSchedule(appointments: [], breaks: []);
  List<Map<String, Object?>> _masters = const [];
  bool _isLoadingCache = true;
  bool _isAdmin = false;
  int? _masterId;
  String? _lastStatusMessage;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _weekStart = _startOfDay(DateTime.now());
    widget.syncService.status.addListener(_onSyncStatusChanged);
    _loadProfileAndCache();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.syncService.status.removeListener(_onSyncStatusChanged);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(widget.syncService.syncNow());
    }
  }

  Future<void> _loadProfileAndCache() async {
    final profile = await widget.syncService.accountProfile();
    final masters = await widget.syncService.database.loadMasters();
    if (!mounted) return;
    setState(() {
      _isAdmin = profile['role'] == 'admin';
      _masterId = (profile['master_id'] as int?) ??
          (masters.isNotEmpty ? masters.first['server_id'] as int? : null);
      _masters = masters;
    });
    await _reloadCache();
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

  void _onSyncStatusChanged() {
    if (!mounted) return;
    final value = widget.syncService.status.value;
    unawaited(_reloadCache());
    unawaited(_reloadMasters());
    final message = value.message;
    if (message != null && message != _lastStatusMessage) {
      _lastStatusMessage = message;
      if (message == 'Зміни синхронізовано з хмарою') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Зміни синхронізовано з хмарою')),
        );
      }
    }
  }

  Future<void> _reloadMasters() async {
    final masters = await widget.syncService.database.loadMasters();
    if (!mounted) return;
    setState(() {
      _masters = masters;
      if (_masterId == null && masters.isNotEmpty) {
        _masterId = masters.first['server_id'] as int?;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final weekEnd = _weekStart.add(const Duration(days: 6));
    final appointments = _schedule.appointments
        .where((item) => _isAdmin || item.masterId == _masterId)
        .toList();
    final breaks = _schedule.breaks
        .where((item) => _isAdmin || item.masterId == _masterId)
        .toList();
    return Scaffold(
      appBar: AppBar(
        title: Text('${_formatDate(_weekStart)} – ${_formatDate(weekEnd)}'),
        actions: [
          if (_isAdmin && _masters.isNotEmpty)
            PopupMenuButton<int>(
              tooltip: 'Обрати майстра',
              icon: const Icon(Icons.person_outline),
              initialValue: _masterId,
              onSelected: (value) {
                setState(() => _masterId = value);
                _reloadCache();
              },
              itemBuilder: (context) => _masters
                  .map((master) => PopupMenuItem<int>(
                        value: master['server_id'] as int,
                        child: Text(master['name']?.toString() ?? 'Майстер'),
                      ))
                  .toList(),
            ),
          IconButton(
            tooltip: 'Зайнятий час',
            onPressed: _addBreak,
            icon: const Icon(Icons.event_busy_outlined),
          ),
          IconButton(
            tooltip: 'Діагностика синхронізації',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => SyncDiagnosticsScreen(
                  syncService: widget.syncService,
                ),
              ),
            ),
            icon: const Icon(Icons.monitor_heart_outlined),
          ),
          IconButton(
            tooltip: 'Вийти',
            onPressed: _logout,
            icon: const Icon(Icons.logout),
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
                      padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                      itemCount: 7,
                      itemBuilder: (context, index) {
                        final day = _weekStart.add(Duration(days: index));
                        final iso = DateFormat('yyyy-MM-dd').format(day);
                        return _DaySection(
                          date: day,
                          appointments: appointments
                              .where((item) => item.date == iso)
                              .toList(),
                          breaks: breaks.where((item) => item.date == iso).toList(),
                          onAppointmentTap: _editAppointment,
                          onAppointmentDelete: _deleteAppointment,
                          onBreakTap: _editBreak,
                          onBreakDelete: _deleteBreak,
                        );
                      },
                    ),
                  ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addAppointment,
        icon: const Icon(Icons.add),
        label: const Text('Новий запис'),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () {
                    setState(() => _weekStart = _weekStart.subtract(const Duration(days: 7)));
                    _reloadCache();
                  },
                  icon: const Icon(Icons.chevron_left),
                  label: const Text('Попередній тиждень'),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filledTonal(
                tooltip: 'Сьогодні',
                onPressed: () {
                  setState(() => _weekStart = _startOfDay(DateTime.now()));
                  _reloadCache();
                },
                icon: const Icon(Icons.today),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () {
                    setState(() => _weekStart = _weekStart.add(const Duration(days: 7)));
                    _reloadCache();
                  },
                  icon: const Icon(Icons.chevron_right),
                  label: const Text('Наступний тиждень'),
                  iconAlignment: IconAlignment.end,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _addAppointment() async {
    final masterId = _masterId;
    if (masterId == null) {
      _showMessage('Спочатку синхронізуйте список майстрів');
      return;
    }
    await _editAppointment(null, initialDate: DateTime.now());
  }

  Future<void> _editAppointment(
    CalendarAppointment? appointment, {
    DateTime? initialDate,
  }) async {
    final masterId = appointment?.masterId ?? _masterId;
    if (masterId == null) {
      _showMessage('Не вдалося визначити майстра для запису');
      return;
    }
    if (appointment?.hasServerConflict == true) {
      final choice = await _showConflictDialog();
      if (choice == 'cloud') {
        await widget.syncService.database.useServerAppointment(appointment!.localId);
        await widget.syncService.hydrate();
        await _reloadCache();
      } else if (choice == 'local') {
        await widget.syncService.database.keepLocalAppointment(appointment!.localId);
        unawaited(widget.syncService.syncNow());
      }
      return;
    }
    final draft = await showDialog<AppointmentDraft>(
      context: context,
      builder: (_) => AppointmentEditor(
        database: widget.syncService.database,
        initialDate: initialDate ?? DateTime.tryParse(appointment?.date ?? '') ?? DateTime.now(),
        appointment: appointment,
      ),
    );
    if (draft == null || !mounted) return;
    final conflict = _findLocalConflict(draft, masterId, appointment?.localId);
    if (conflict != null) {
      final continueSaving = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Час може бути зайнятий'),
          content: Text(
            'У кеші є подія «${conflict.clientName}» на цей час. Календар може бути застарілим; сервер перевірить час під час синхронізації. Зберегти запис на телефоні?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Перевірити пізніше'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Зберегти на телефоні'),
            ),
          ],
        ),
      );
      if (continueSaving != true) return;
    }
    await widget.syncService.saveAppointment(
      existing: appointment,
      masterId: masterId,
      clientName: draft.clientName,
      phone: draft.phone,
      service: draft.service,
      serviceIds: draft.serviceIds,
      clientId: draft.clientId,
      date: draft.date,
      startTime: draft.startTime,
      durationMin: draft.durationMin,
      notes: draft.notes,
      appointmentStatus: draft.status,
    );
    await _reloadCache();
    _showMessage(widget.syncService.status.value.isOnline
        ? 'Збережено на телефоні. Синхронізуємо з хмарою…'
        : 'Збережено на телефоні. Надішлемо, коли з’явиться мережа.');
  }

  Future<void> _deleteAppointment(CalendarAppointment appointment) async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Видалити запис?'),
        content: Text('Запис для ${appointment.clientName} буде видалено з календаря.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Скасувати')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Видалити')),
        ],
      ),
    );
    if (accepted != true) return;
    await widget.syncService.deleteAppointment(appointment);
    await _reloadCache();
    _showMessage(widget.syncService.status.value.isOnline
        ? 'Запис видалено з телефона. Синхронізуємо…'
        : 'Запис видалено з телефона. Зміна надішлеться після відновлення мережі.');
  }

  Future<void> _addBreak() => _editBreak(null, initialDate: DateTime.now());

  Future<void> _editBreak(CalendarBreak? item, {DateTime? initialDate}) async {
    final masterId = item?.masterId ?? _masterId;
    if (masterId == null) {
      _showMessage('Спочатку синхронізуйте список майстрів');
      return;
    }
    if (item?.hasServerConflict == true) {
      final choice = await _showConflictDialog();
      if (choice == 'cloud') {
        await widget.syncService.database.useServerBreak(item!.localId);
        await widget.syncService.hydrate();
        await _reloadCache();
      } else if (choice == 'local') {
        await widget.syncService.database.keepLocalBreak(item!.localId);
        unawaited(widget.syncService.syncNow());
      }
      return;
    }
    final draft = await showDialog<BreakDraft>(
      context: context,
      builder: (_) => BreakEditor(
        initialDate: initialDate ?? DateTime.tryParse(item?.date ?? '') ?? DateTime.now(),
        item: item,
      ),
    );
    if (draft == null || !mounted) return;
    await widget.syncService.saveBreak(
      existing: item,
      masterId: masterId,
      date: draft.date,
      startTime: draft.startTime,
      endTime: draft.endTime,
      label: draft.label,
    );
    await _reloadCache();
    _showMessage(widget.syncService.status.value.isOnline
        ? 'Час збережено на телефоні. Синхронізуємо…'
        : 'Час збережено на телефоні. Надішлемо після відновлення мережі.');
  }

  Future<void> _deleteBreak(CalendarBreak item) async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Видалити блокування?'),
        content: Text('«${item.label}» буде видалено з календаря.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Скасувати')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Видалити')),
        ],
      ),
    );
    if (accepted != true) return;
    await widget.syncService.deleteBreak(item);
    await _reloadCache();
    _showMessage('Блокування видалено з телефона.');
  }

  CalendarAppointment? _findLocalConflict(
    AppointmentDraft draft,
    int masterId,
    String? excludedLocalId,
  ) {
    final start = _minutes(draft.startTime);
    final end = start + draft.durationMin;
    for (final item in _schedule.appointments) {
      if (item.masterId != masterId || item.date != draft.date || item.localId == excludedLocalId) {
        continue;
      }
      final otherStart = _minutes(item.startTime);
      if (start < otherStart + item.durationMin && end > otherStart) return item;
    }
    for (final item in _schedule.breaks) {
      if (item.masterId != masterId || item.date != draft.date) continue;
      if (start < _minutes(item.endTime) && end > _minutes(item.startTime)) {
        return CalendarAppointment(
          localId: item.localId,
          serverId: item.serverId,
          masterId: item.masterId,
          clientName: item.label,
          service: 'Зайнятий час',
          serviceIds: const [],
          date: item.date,
          startTime: item.startTime,
          durationMin: _minutes(item.endTime) - _minutes(item.startTime),
          status: 'scheduled',
          version: item.version,
          isPending: item.isPending,
        );
      }
    }
    return null;
  }

  Future<String?> _showConflictDialog() => showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Запис змінено в хмарі'),
          content: const Text(
            'На іншому пристрої цей запис уже оновили. Оберіть, яку версію залишити.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Пізніше'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, 'cloud'),
              child: const Text('Взяти з хмари'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, 'local'),
              child: const Text('Залишити з телефона'),
            ),
          ],
        ),
      );

  Future<void> _logout() async {
    final pending = widget.syncService.status.value.pendingCount;
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Вийти із застосунку?'),
        content: Text(pending > 0
            ? 'Є $pending змін, які ще не синхронізовані. Вони залишаться на телефоні й будуть доступні після повторного входу в цей профіль.'
            : 'Локальний календар залишиться на телефоні.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Скасувати')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Вийти')),
        ],
      ),
    );
    if (accepted != true || !mounted) return;
    try {
      await widget.apiClient.logout();
    } catch (_) {
      // The local session is cleared even when the server cannot be reached.
    }
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => LoginScreen(
          apiClient: widget.apiClient,
          syncService: widget.syncService,
        ),
      ),
      (_) => false,
    );
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  DateTime _startOfDay(DateTime value) => DateTime(value.year, value.month, value.day);

  String _formatDate(DateTime value) => DateFormat('dd.MM').format(value);

  int _minutes(String value) {
    final parts = value.split(':');
    return (int.tryParse(parts.first) ?? 0) * 60 +
        (parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0);
  }
}

class _SyncBanner extends StatelessWidget {
  const _SyncBanner({required this.status, required this.onSync});

  final SyncStatus status;
  final Future<void> Function() onSync;

  @override
  Widget build(BuildContext context) {
    final color = status.isOnline ? Colors.greenAccent : Colors.orangeAccent;
    final label = status.failedCount > 0
        ? 'Потрібна увага: ${status.failedCount} · очікує ${status.pendingCount}'
        : status.pendingCount > 0
            ? 'На телефоні збережено · очікує синхронізації: ${status.pendingCount}'
            : status.isSyncing
                ? 'Синхронізуємо…'
                : status.isOnline
                    ? 'Синхронізовано'
                    : 'Офлайн · показуємо дані телефона';
    final lastSync = status.lastSyncAt == null
        ? 'Ще не синхронізовано'
        : 'Остання синхронізація ${DateFormat('dd.MM HH:mm').format(status.lastSyncAt!.toLocal())}';
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            Icon(Icons.circle, size: 10, color: color),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
                  Text(lastSync, style: Theme.of(context).textTheme.bodySmall),
                  if (status.error != null)
                    Text(
                      status.error!,
                      style: TextStyle(color: Theme.of(context).colorScheme.error),
                    ),
                ],
              ),
            ),
            if (status.isSyncing)
              const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              IconButton(
                tooltip: 'Синхронізувати зараз',
                onPressed: onSync,
                icon: const Icon(Icons.sync),
              ),
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
    required this.onAppointmentTap,
    required this.onAppointmentDelete,
    required this.onBreakTap,
    required this.onBreakDelete,
  });

  final DateTime date;
  final List<CalendarAppointment> appointments;
  final List<CalendarBreak> breaks;
  final ValueChanged<CalendarAppointment> onAppointmentTap;
  final ValueChanged<CalendarAppointment> onAppointmentDelete;
  final ValueChanged<CalendarBreak> onBreakTap;
  final ValueChanged<CalendarBreak> onBreakDelete;

  @override
  Widget build(BuildContext context) {
    final events = <({String time, Widget widget})>[
      ...appointments.map((item) => (
            time: item.startTime,
            widget: _AppointmentTile(
              item: item,
              onTap: () => onAppointmentTap(item),
              onDelete: () => onAppointmentDelete(item),
            ),
          )),
      ...breaks.map((item) => (
            time: item.startTime,
            widget: _BreakTile(
              item: item,
              onTap: () => onBreakTap(item),
              onDelete: () => onBreakDelete(item),
            ),
          )),
    ]..sort((a, b) => a.time.compareTo(b.time));

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              DateFormat('EEEE, dd.MM', 'uk').format(date),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            if (events.isEmpty)
              Text(
                'Немає записів',
                style: TextStyle(color: Theme.of(context).colorScheme.outline),
              )
            else
              ...events.map((event) => event.widget),
          ],
        ),
      ),
    );
  }
}

class _AppointmentTile extends StatelessWidget {
  const _AppointmentTile({
    required this.item,
    required this.onTap,
    required this.onDelete,
  });

  final CalendarAppointment item;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final color = item.syncError != null
        ? Theme.of(context).colorScheme.error
        : Theme.of(context).colorScheme.primary;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(item.isPending ? Icons.cloud_upload_outlined : Icons.event_available, color: color),
      title: Text('${item.startTime} · ${item.clientName}'),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${item.service} · ${item.durationMin} хв · ${_statusLabel(item.status)}'),
          if (item.syncError != null)
            Text(item.syncError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
      ),
      trailing: IconButton(
        tooltip: 'Видалити запис',
        onPressed: onDelete,
        icon: const Icon(Icons.delete_outline),
      ),
      onTap: onTap,
    );
  }

  String _statusLabel(String value) => const {
        'scheduled': 'Заплановано',
        'confirmed': 'Підтверджено',
        'completed': 'Виконано',
        'cancelled': 'Скасовано',
        'no_show': 'Не прийшов',
      }[value] ?? value;
}

class _BreakTile extends StatelessWidget {
  const _BreakTile({required this.item, required this.onTap, required this.onDelete});

  final CalendarBreak item;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(
          item.isPending ? Icons.cloud_upload_outlined : Icons.block,
          color: Theme.of(context).colorScheme.tertiary,
        ),
        title: Text('${item.startTime}-${item.endTime} · ${item.label}'),
        subtitle: Text(item.syncError ?? 'Зайнятий час'),
        trailing: IconButton(
          tooltip: 'Видалити блокування',
          onPressed: onDelete,
          icon: const Icon(Icons.delete_outline),
        ),
        onTap: onTap,
      );
}
