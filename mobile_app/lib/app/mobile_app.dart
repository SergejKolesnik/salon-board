import 'package:flutter/material.dart';

import '../core/api/api_client.dart';
import '../core/db/local_database.dart';
import '../core/sync/sync_service.dart';
import '../features/auth/login_screen.dart';

class SalonBoardMobileApp extends StatefulWidget {
  const SalonBoardMobileApp({super.key});

  @override
  State<SalonBoardMobileApp> createState() => _SalonBoardMobileAppState();
}

class _SalonBoardMobileAppState extends State<SalonBoardMobileApp> {
  late final LocalDatabase database;
  late final ApiClient apiClient;
  late final SyncService syncService;

  @override
  void initState() {
    super.initState();
    database = LocalDatabase();
    apiClient = ApiClient();
    syncService = SyncService(apiClient: apiClient, database: database);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Body Balance CRM',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF00C8B4),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: LoginScreen(apiClient: apiClient, syncService: syncService),
    );
  }
}
