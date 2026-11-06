class SyncStatus {
  const SyncStatus({
    required this.isOnline,
    required this.isSyncing,
    this.lastSyncAt,
    this.error,
    this.message,
    this.pendingCount = 0,
    this.failedCount = 0,
  });

  final bool isOnline;
  final bool isSyncing;
  final DateTime? lastSyncAt;
  final String? error;
  final String? message;
  final int pendingCount;
  final int failedCount;

  SyncStatus copyWith({
    bool? isOnline,
    bool? isSyncing,
    DateTime? lastSyncAt,
    String? error,
    String? message,
    int? pendingCount,
    int? failedCount,
    bool clearError = false,
    bool clearMessage = false,
    bool clearLastSyncAt = false,
  }) {
    return SyncStatus(
      isOnline: isOnline ?? this.isOnline,
      isSyncing: isSyncing ?? this.isSyncing,
      lastSyncAt: clearLastSyncAt ? null : lastSyncAt ?? this.lastSyncAt,
      error: clearError ? null : error ?? this.error,
      message: clearMessage ? null : message ?? this.message,
      pendingCount: pendingCount ?? this.pendingCount,
      failedCount: failedCount ?? this.failedCount,
    );
  }
}
