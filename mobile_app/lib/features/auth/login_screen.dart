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
  final _masterIdController = TextEditingController();
  bool _isLoading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    widget.syncService.hydrate();
  }

  @override
  void dispose() {
    _passwordController.dispose();
    _masterIdController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Salon Board Mobile',
                    style: Theme.of(context).textTheme.headlineMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Read-only offline prototype',
                    style: Theme.of(context).textTheme.bodyMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 28),
                  TextField(
                    controller: _passwordController,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Пароль',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _masterIdController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'ID майстра, якщо вхід як майстер',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Colors.red)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _isLoading ? null : _loginAndSync,
                    child: _isLoading
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Увійти і синхронізувати'),
                  ),
                  const SizedBox(height: 8),
                  OutlinedButton(
                    onPressed: _isLoading ? null : _openCachedCalendar,
                    child: const Text('Відкрити кешований календар'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _loginAndSync() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final masterId = int.tryParse(_masterIdController.text.trim());
      await widget.apiClient.login(
        password: _passwordController.text,
        masterId: masterId,
      );
      await widget.syncService.syncNow();
      if (!mounted) return;
      _openCalendar();
    } catch (error) {
      setState(() => _error = 'Помилка входу: $error');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _openCachedCalendar() {
    _openCalendar();
  }

  void _openCalendar() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => CalendarScreen(syncService: widget.syncService),
      ),
    );
  }
}
