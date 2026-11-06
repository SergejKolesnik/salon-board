import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../core/sync/sync_service.dart';
import '../../core/sync/sync_status.dart';

class SyncDiagnosticsScreen extends StatefulWidget {
  const SyncDiagnosticsScreen({required this.syncService, super.key});

  final SyncService syncService;

  @override
  State<SyncDiagnosticsScreen> createState() => _SyncDiagnosticsScreenState();
}

class _SyncDiagnosticsScreenState extends State<SyncDiagnosticsScreen> {
  String _appVersion = 'unknown';
  int _dbSizeBytes = 0;
  int _appointmentsCount = 0;
  int _clientsCount = 0;
  int _breaksCount = 0;
  int _pendingCount = 0;
  int _failedCount = 0;

  @override
  void initState() {
    super.initState();
    widget.syncService.status.addListener(_reload);
    _reload();
  }

  @override
  void dispose() {
    widget.syncService.status.removeListener(_reload);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
      return Scaffold(
      appBar: AppBar(title: const Text('Діагностика синхронізації')),
      body: ValueListenableBuilder<SyncStatus>(
        valueListenable: widget.syncService.status,
        builder: (context, status, _) {
          final lastSync = status.lastSyncAt == null
              ? 'Ще не було'
              : DateFormat('dd.MM.yyyy HH:mm:ss').format(
                  status.lastSyncAt!.toLocal(),
                );
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _DiagnosticTile(
                label: 'Мережа',
                value: status.isOnline ? 'Є підключення' : 'Офлайн',
              ),
              _DiagnosticTile(label: 'Остання синхронізація', value: lastSync),
              _DiagnosticTile(label: 'Версія застосунку', value: _appVersion),
              _DiagnosticTile(
                label: 'Розмір локальної бази',
                value: _formatBytes(_dbSizeBytes),
              ),
              _DiagnosticTile(
                label: 'Записів у базі',
                value: _appointmentsCount.toString(),
              ),
              _DiagnosticTile(
                label: 'Клієнтів у базі',
                value: _clientsCount.toString(),
              ),
              _DiagnosticTile(
                label: 'Блокувань у базі',
                value: _breaksCount.toString(),
              ),
              _DiagnosticTile(label: 'Очікує відправлення', value: '$_pendingCount'),
              _DiagnosticTile(label: 'Помилок синхронізації', value: '$_failedCount'),
              if (status.error != null)
                _DiagnosticTile(label: 'Остання помилка', value: status.error!),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: status.isSyncing
                    ? null
                    : () async {
                        await widget.syncService.syncNow();
                        await _reload();
                      },
                icon: const Icon(Icons.sync),
                label: Text(status.isSyncing ? 'Синхронізуємо…' : 'Синхронізувати зараз'),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _reload() async {
    final packageInfo = await PackageInfo.fromPlatform();
    final db = widget.syncService.database;
    final dbSize = await db.databaseSizeBytes();
    final appointments = await db.countAppointments();
    final clients = await db.countClients();
    final breaks = await db.countBreaks();
    final pending = await db.pendingCount();
    final failed = await db.failedCount();

    if (!mounted) return;
    setState(() {
      _appVersion = '${packageInfo.version}+${packageInfo.buildNumber}';
      _dbSizeBytes = dbSize;
      _appointmentsCount = appointments;
      _clientsCount = clients;
      _breaksCount = breaks;
      _pendingCount = pending;
      _failedCount = failed;
    });
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    final kb = bytes / 1024;
    if (kb < 1024) return '${kb.toStringAsFixed(1)} KB';
    final mb = kb / 1024;
    return '${mb.toStringAsFixed(2)} MB';
  }
}

class _DiagnosticTile extends StatelessWidget {
  const _DiagnosticTile({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        title: Text(label),
        subtitle: Text(value),
      ),
    );
  }
}
