class SyncStatus {
  const SyncStatus({
    required this.isOnline,
    required this.isSyncing,
    this.lastSyncAt,
    this.error,
  });

  final bool isOnline;
  final bool isSyncing;
  final DateTime? lastSyncAt;
  final String? error;

  SyncStatus copyWith({
    bool? isOnline,
    bool? isSyncing,
    DateTime? lastSyncAt,
    String? error,
    bool clearError = false,
  }) {
    return SyncStatus(
      isOnline: isOnline ?? this.isOnline,
      isSyncing: isSyncing ?? this.isSyncing,
      lastSyncAt: lastSyncAt ?? this.lastSyncAt,
      error: clearError ? null : error ?? this.error,
    );
  }
}
