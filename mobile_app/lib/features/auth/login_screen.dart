import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/api/api_client.dart';
import '../../core/sync/sync_service.dart';
import '../calendar/calendar_screen.dart';

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
  final _passwordController = TextEditingController();
  List<Map<String, Object?>> _masters = const [];
  String? _selectedProfile;
  bool _isLoading = false;
  bool _isInitializing = true;
  bool _mastersLoaded = false;
  bool _mastersLoadFailed = false;
  bool _userSelectedProfile = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  @override
  void dispose() {
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _initialize() async {
    await widget.syncService.hydrate();
    final hasSession = await widget.apiClient.hasSession();
    final profile = await widget.syncService.accountProfile();
    if (!mounted) return;
    if (hasSession && (profile['role'] as String? ?? '').isNotEmpty) {
      _openCalendar();
      unawaited(widget.syncService.syncNow());
      return;
    }

    final cachedMasters = await widget.syncService.database.loadMasters();
    final masters = cachedMasters;
    setState(() {
      _masters = masters;
      if (masters.isNotEmpty) {
        _selectedProfile =
            'master:${masters.first['id'] ?? masters.first['server_id']}';
        _mastersLoaded = true;
      }
      _isInitializing = false;
    });
    unawaited(_refreshMasterList());
    if (hasSession) unawaited(_restoreUnscopedSession());
  }

  Future<void> _refreshMasterList() async {
    try {
      final response = await widget.apiClient.masters();
      final masters = response
          .whereType<Map>()
          .map((item) => Map<String, Object?>.from(item))
          .toList();
      if (!mounted) return;
      setState(() {
        _masters = masters;
        _mastersLoaded = true;
        _mastersLoadFailed = false;
        if (!_userSelectedProfile && _selectedProfile == null) {
          _selectedProfile = masters.isNotEmpty
              ? 'master:${masters.first['id'] ?? masters.first['server_id']}'
              : 'admin';
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _mastersLoaded = true;
        _mastersLoadFailed = true;
        if (!_userSelectedProfile &&
            _selectedProfile == null &&
            _masters.isNotEmpty) {
          _selectedProfile =
              'master:${_masters.first['id'] ?? _masters.first['server_id']}';
        }
      });
    }
  }

  Future<void> _restoreUnscopedSession() async {
    try {
      final me = await widget.apiClient.currentUser();
      await widget.syncService.setAccountProfile(
        me['role']?.toString() ?? '',
        _asInt(me['master_id']),
      );
      if (!mounted) return;
      _openCalendar();
      unawaited(widget.syncService.syncNow());
    } catch (_) {
      // Keep the cached calendar available through the manual offline button.
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isInitializing) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.all(20),
              children: [
                Center(
                  child: Image.asset(
                    'assets/branding/splash_logo.png',
                    height: 92,
                    fit: BoxFit.contain,
                    semanticLabel: 'Логотип Body Balance',
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  'Body Balance CRM',
                  style: Theme.of(context).textTheme.headlineMedium,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),
                Text(
                  'Оберіть свій профіль, потім введіть відповідний пароль.',
                  style: Theme.of(context).textTheme.bodyMedium,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 28),
                DropdownButtonFormField<String>(
                  key: ValueKey(_selectedProfile),
                  initialValue: _selectedProfile,
                  decoration: const InputDecoration(
                    labelText: 'Профіль',
                    border: OutlineInputBorder(),
                  ),
                  hint: Text(
                    _mastersLoaded ? 'Оберіть профіль' : 'Завантажуємо профілі…',
                  ),
                  items: [
                    const DropdownMenuItem(
                        value: 'admin', child: Text('Адміністратор')),
                    if (!_mastersLoaded && _masters.isEmpty)
                      const DropdownMenuItem<String>(
                        value: '__loading__',
                        enabled: false,
                        child: Text('Майстри з’являться після завантаження'),
                      ),
                    ..._masters.map((master) {
                      final id = master['id'] ?? master['server_id'];
                      return DropdownMenuItem(
                        value: 'master:$id',
                        child: Text(master['name']?.toString() ?? 'Майстер'),
                      );
                    }),
                  ],
                  onChanged: (value) => setState(() {
                    _userSelectedProfile = true;
                    _selectedProfile = value;
                  }),
                ),
                if (!_mastersLoaded) ...[
                  const SizedBox(height: 8),
                  const LinearProgressIndicator(minHeight: 2),
                  const SizedBox(height: 6),
                  Text(
                    'Завантажуємо профілі майстрів із сервера. Дочекайтеся імені Оксани, щоб увійти як майстер.',
                    style: Theme.of(context).textTheme.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                ] else if (_mastersLoadFailed) ...[
                  const SizedBox(height: 8),
                  Text(
                    'Не вдалося завантажити профілі майстрів. Перевірте мережу й повторіть спробу.',
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                    textAlign: TextAlign.center,
                  ),
                  TextButton(
                    onPressed: _refreshMasterList,
                    child: const Text('Оновити список профілів'),
                  ),
                ],
                const SizedBox(height: 12),
                TextField(
                  controller: _passwordController,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Пароль',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _loginAndOpen(),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _isLoading || _selectedProfile == null
                      ? null
                      : _loginAndOpen,
                  child: _isLoading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Увійти'),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: _openCachedCalendar,
                  child: const Text('Відкрити дані з телефона'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _loginAndOpen() async {
    if (_selectedProfile == null) {
      setState(() => _error = 'Спочатку оберіть профіль: адміністратора або Оксану.');
      return;
    }
    final password = _passwordController.text;
    if (password.isEmpty) {
      setState(() => _error = 'Введіть пароль');
      return;
    }
    final previousScope = await widget.syncService.database.accountScope();
    final pending = await widget.syncService.database.pendingCount();
    final requestedScope =
        _selectedProfile == 'admin' ? 'admin' : _selectedProfile!;
    if (previousScope != null &&
        previousScope != requestedScope &&
        pending > 0) {
      setState(() => _error =
          'На телефоні є несинхронізовані зміни профілю $previousScope. Увійдіть у нього й синхронізуйте їх перед зміною профілю.');
      return;
    }
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final selectedProfile = _selectedProfile!;
      final masterId = selectedProfile.startsWith('master:')
          ? int.tryParse(selectedProfile.substring('master:'.length))
          : null;
      final response = await widget.apiClient.login(
        password: password,
        masterId: masterId,
      );
      final role = response['role']?.toString() ?? '';
      final actualMasterId = _asInt(response['master_id']);
      final actualScope =
          role == 'master' ? 'master:${actualMasterId ?? 0}' : 'admin';
      if (previousScope != null &&
          previousScope != actualScope &&
          pending > 0) {
        await widget.apiClient.logout();
        throw StateError(
          'Спочатку синхронізуйте зміни профілю $previousScope або увійдіть у нього знову.',
        );
      }
      await widget.syncService.setAccountProfile(role, actualMasterId);
      if (!mounted) return;
      _passwordController.clear();
      _openCalendar();
      unawaited(widget.syncService.syncNow());
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _openCachedCalendar() async {
    final profile = await widget.syncService.accountProfile();
    if ((profile['role'] as String? ?? '').isEmpty &&
        _masters.isNotEmpty &&
        _selectedProfile?.startsWith('master:') == true) {
      final masterId = int.tryParse(_selectedProfile!.split(':').last);
      await widget.syncService.setAccountProfile('master', masterId);
    }
    if (!mounted) return;
    _openCalendar();
    unawaited(widget.syncService.syncNow());
  }

  void _openCalendar() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => CalendarScreen(
          syncService: widget.syncService,
          apiClient: widget.apiClient,
        ),
      ),
    );
  }

  String _friendlyError(Object error) {
    final text = error.toString().toLowerCase();
    if (text.contains('401') || text.contains('невірний пароль')) {
      return 'Невірний пароль або профіль';
    }
    if (text.contains('зміни профілю')) {
      return error.toString().replaceFirst('Bad state: ', '');
    }
    return 'Не вдалося увійти. Перевірте мережу та пароль.';
  }

  int? _asInt(Object? value) {
    if (value is int) return value;
    return value == null ? null : int.tryParse(value.toString());
  }
}
