import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../db/local_database.dart';
import 'sync_status.dart';

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

  final ValueNotifier<SyncStatus> status = ValueNotifier(
    const SyncStatus(isOnline: true, isSyncing: false),
  );

  LocalDatabase get database => _database;

  Future<void> hydrate() async {
    final lastSyncAt = await _database.loadLastSyncAt();
    status.value = status.value.copyWith(lastSyncAt: lastSyncAt);
  }

  Future<void> syncNow() async {
    if (!status.value.isOnline) {
      status.value = status.value.copyWith(
        isSyncing: false,
        error: 'Offline: показуємо кешовані дані',
      );
      return;
    }

    status.value = status.value.copyWith(isSyncing: true, clearError: true);
    try {
      final payload = await _apiClient.bootstrap();
      await _database.saveBootstrap(payload);
      final lastSyncAt = await _database.loadLastSyncAt();
      status.value = status.value.copyWith(
        isSyncing: false,
        lastSyncAt: lastSyncAt,
        clearError: true,
      );
    } catch (error) {
      status.value = status.value.copyWith(
        isSyncing: false,
        error: 'Не вдалося синхронізувати: $error',
      );
    }
  }

  Future<void> dispose() async {
    await _connectivitySub?.cancel();
    status.dispose();
  }

  Future<void> _initConnectivity() async {
    final initial = await _connectivity.checkConnectivity();
    _setConnectivity(initial);
    _connectivitySub = _connectivity.onConnectivityChanged.listen(
      _setConnectivity,
    );
  }

  void _setConnectivity(List<ConnectivityResult> results) {
    final isOnline = results.any((result) => result != ConnectivityResult.none);
    status.value = status.value.copyWith(isOnline: isOnline);
  }
}
