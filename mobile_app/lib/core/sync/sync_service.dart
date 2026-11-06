import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../features/calendar/calendar_models.dart';
import '../api/api_client.dart';
import '../db/local_database.dart';
import 'sync_status.dart';

/// Coordinates local-first writes, durable retries, and server reconciliation.
class SyncService {
  SyncService({required ApiClient apiClient, required LocalDatabase database})
      : _apiClient = apiClient,
        _database = database {
    _initConnectivity();
  }

  final ApiClient _apiClient;
  final LocalDatabase _database;
  final Connectivity _connectivity = Connectivity();
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  Timer? _reconnectTimer;
  Future<void>? _activeSync;
  bool _wasOnline = false;

  final ValueNotifier<SyncStatus> status = ValueNotifier(
    const SyncStatus(isOnline: false, isSyncing: false),
  );

  LocalDatabase get database => _database;

  Future<void> hydrate() async {
    final lastSyncAt = await _database.loadLastSyncAt();
    final pendingCount = await _database.pendingCount();
    final failedCount = await _database.failedCount();
    status.value = status.value.copyWith(
      lastSyncAt: lastSyncAt,
      pendingCount: pendingCount,
      failedCount: failedCount,
      clearLastSyncAt: true,
    );
  }

  Future<Map<String, Object?>> accountProfile() => _database.accountProfile();

  Future<void> setAccountProfile(String role, int? masterId) async {
    await _database.setAccountProfile(role, masterId);
    await hydrate();
  }

  Future<CalendarAppointment> saveAppointment({
    required CalendarAppointment? existing,
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
    required String appointmentStatus,
  }) async {
    final appointment = await _database.saveAppointment(
      localId: existing?.localId,
      serverId: existing?.serverId,
      masterId: masterId,
      clientName: clientName,
      phone: phone,
      service: service,
      serviceIds: serviceIds,
      clientId: clientId,
      date: date,
      startTime: startTime,
      durationMin: durationMin,
      notes: notes,
      status: appointmentStatus,
      baseVersion: existing?.version,
    );
    await _refreshQueueCounts();
    if (status.value.isOnline) unawaited(syncNow());
    return appointment;
  }

  Future<void> deleteAppointment(CalendarAppointment appointment) async {
    await _database.deleteAppointment(appointment);
    await _refreshQueueCounts();
    if (status.value.isOnline) unawaited(syncNow());
  }

  Future<CalendarBreak> saveBreak({
    required CalendarBreak? existing,
    required int masterId,
    required String date,
    required String startTime,
    required String endTime,
    required String label,
  }) async {
    final item = await _database.saveBreak(
      localId: existing?.localId,
      serverId: existing?.serverId,
      masterId: masterId,
      date: date,
      startTime: startTime,
      endTime: endTime,
      label: label,
      baseVersion: existing?.version,
    );
    await _refreshQueueCounts();
    if (status.value.isOnline) unawaited(syncNow());
    return item;
  }

  Future<void> deleteBreak(CalendarBreak item) async {
    await _database.deleteBreak(item);
    await _refreshQueueCounts();
    if (status.value.isOnline) unawaited(syncNow());
  }

  Future<void> syncNow() {
    final active = _activeSync;
    if (active != null) return active;
    final future = _runSync();
    _activeSync = future;
    return future.whenComplete(() => _activeSync = null);
  }

  Future<void> _runSync() async {
    if (!status.value.isOnline) {
      await _refreshQueueCounts();
      return;
    }
    status.value = status.value.copyWith(
      isSyncing: true,
      clearError: true,
      clearMessage: true,
    );
    var pushedCount = 0;
    try {
      final pending = await _database.pendingChanges();
      if (pending.isNotEmpty) {
        final pushResult = await _apiClient.push(pending);
        await _database.applyPushResult(pushResult);
        pushedCount = ((pushResult['mappings'] as Map?)?.values ?? const [])
            .whereType<List>()
            .fold<int>(0, (sum, values) => sum + values.length);
      }

      final lastSyncAt = await _database.loadLastSyncAt();
      if (lastSyncAt == null) {
        await _database.saveBootstrap(await _apiClient.bootstrap());
      } else {
        await _database.applyPull(
          await _apiClient.pull(lastSyncAt.toUtc().toIso8601String()),
        );
      }

      final pendingCount = await _database.pendingCount();
      final failedCount = await _database.failedCount();
      final lastSuccessfulSync = await _database.loadLastSyncAt();
      status.value = status.value.copyWith(
        isSyncing: false,
        lastSyncAt: lastSuccessfulSync,
        pendingCount: pendingCount,
        failedCount: failedCount,
        message: failedCount > 0
            ? 'Є зміни, які потребують уваги'
            : pushedCount > 0
                ? 'Зміни синхронізовано з хмарою'
                : 'Розклад оновлено',
        clearError: true,
      );
    } catch (error) {
      final counts = await _readQueueCounts();
      final isUnauthorized = error is DioException && error.response?.statusCode == 401;
      status.value = status.value.copyWith(
        isSyncing: false,
        pendingCount: counts.$1,
        failedCount: counts.$2,
        error: isUnauthorized
            ? 'Сесія завершилася. Увійдіть знову; локальні зміни збережені.'
            : 'Не вдалося синхронізувати. Локальні зміни збережені й будуть надіслані пізніше.',
        clearMessage: true,
      );
    }
  }

  Future<void> _refreshQueueCounts() async {
    final counts = await _readQueueCounts();
    status.value = status.value.copyWith(
      pendingCount: counts.$1,
      failedCount: counts.$2,
    );
  }

  Future<(int, int)> _readQueueCounts() async => (
        await _database.pendingCount(),
        await _database.failedCount(),
      );

  Future<void> dispose() async {
    _reconnectTimer?.cancel();
    await _connectivitySub?.cancel();
    status.dispose();
  }

  Future<void> _initConnectivity() async {
    final initial = await _connectivity.checkConnectivity();
    _setConnectivity(initial);
    _connectivitySub = _connectivity.onConnectivityChanged.listen(_setConnectivity);
  }

  void _setConnectivity(List<ConnectivityResult> results) {
    final isOnline = results.any((result) => result != ConnectivityResult.none);
    final reconnected = isOnline && !_wasOnline;
    _wasOnline = isOnline;
    status.value = status.value.copyWith(isOnline: isOnline);
    if (reconnected) {
      _reconnectTimer?.cancel();
      _reconnectTimer = Timer(const Duration(seconds: 1), () {
        if (status.value.pendingCount > 0 || status.value.lastSyncAt != null) {
          unawaited(syncNow());
        }
      });
    }
  }
}
