import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/api/api_client.dart';
import '../../core/sync/sync_service.dart';
import '../pwa/pwa_screen.dart';

/// Starts the single-master mobile app without asking for a password.
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    required this.apiClient,
    required this.syncService,
    super.key,
  });

  final ApiClient apiClient;
  final SyncService syncService;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool _isOpening = true;
  String? _error;
  bool _hasLocalCalendar = false;

  @override
  void initState() {
    super.initState();
    unawaited(_open());
  }

  Future<void> _open() async {
    if (!mounted) return;
    setState(() {
      _isOpening = true;
      _error = null;
    });

    try {
      await widget.syncService.hydrate();
      final profile = await widget.syncService.accountProfile();
      final hasSession = await widget.apiClient.hasSession();

      if (hasSession &&
          profile['role'] == 'master' &&
          _asInt(profile['master_id']) != null) {
        _openCalendar();
        unawaited(widget.syncService.syncNow());
        return;
      }

      final session = await widget.apiClient.openMobileSession();
      final role = session['role']?.toString() ?? '';
      final masterId = _asInt(session['master_id']);
      if (role != 'master' || masterId == null) {
        throw StateError('Сервер не повернув профіль майстра для мобільного застосунку.');
      }
      await widget.syncService.setAccountProfile(role, masterId);
      if (!mounted) return;
      _openCalendar();
      unawaited(widget.syncService.syncNow());
    } catch (error) {
      await _openCachedCalendarIfAvailable();
      if (!mounted || _hasLocalCalendar) return;
      setState(() {
        _isOpening = false;
        _error = _friendlyError(error);
      });
    }
  }

  Future<void> _openCachedCalendarIfAvailable() async {
    final profile = await widget.syncService.accountProfile();
    var hasSavedMasterProfile = profile['role'] == 'master' &&
        _asInt(profile['master_id']) != null;
    final masters = await widget.syncService.database.loadMasters();
    final hasCachedMaster = masters.any(
      (master) => _asInt(master['server_id']) != null,
    );
    if (!hasSavedMasterProfile && hasCachedMaster) {
      final masterId = _asInt(masters.first['server_id']);
      if (masterId != null) {
        try {
          await widget.syncService.setAccountProfile('master', masterId);
          hasSavedMasterProfile = true;
        } on StateError {
          // Preserve the current account and its pending changes.
        }
      }
    }

    _hasLocalCalendar = hasSavedMasterProfile;
    if (!_hasLocalCalendar || !mounted) return;
    _openCalendar();
    unawaited(widget.syncService.syncNow());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Image.asset(
                    'assets/branding/splash_logo.png',
                    height: 92,
                    fit: BoxFit.contain,
                    semanticLabel: 'Логотип Body Balance',
                  ),
                  const SizedBox(height: 24),
                  if (_isOpening) ...[
                    const CircularProgressIndicator(),
                    const SizedBox(height: 16),
                    const Text('Відкриваємо розклад…'),
                  ] else ...[
                    Text(
                      _error ?? 'Не вдалося відкрити розклад.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      onPressed: _open,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Повторити'),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _openCalendar() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => PwaScreen(apiClient: widget.apiClient),
      ),
    );
  }

  String _friendlyError(Object error) {
    final message = error.toString().toLowerCase();
    if (message.contains('503') || message.contains('одним активним майстром')) {
      return 'Автоматичний доступ налаштований для одного активного майстра. Перевірте список майстрів на сервері.';
    }
    if (message.contains('connection') || message.contains('timeout')) {
      return 'Немає зв’язку із сервером. Для першого запуску потрібен інтернет.';
    }
    return 'Не вдалося відкрити розклад. Перевірте інтернет і спробуйте ще раз.';
  }

  int? _asInt(Object? value) {
    if (value is int) return value;
    return value == null ? null : int.tryParse(value.toString());
  }
}
