import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../core/api/api_client.dart';
import '../../core/sync/sync_service.dart';
import 'pwa_bridge.dart';

/// Shows the existing Body Balance PWA inside the Android application.
class PwaScreen extends StatefulWidget {
  const PwaScreen({required this.apiClient, required this.syncService, super.key});

  final ApiClient apiClient;
  final SyncService syncService;

  @override
  State<PwaScreen> createState() => _PwaScreenState();
}

class _PwaScreenState extends State<PwaScreen> {
  final WebViewCookieManager _cookies = WebViewCookieManager();
  WebViewController? _controller;
  String? _error;
  bool _loading = true;
  bool _refreshingSession = false;
  DateTime? _lastRenderedSync;

  @override
  void initState() {
    super.initState();
    widget.syncService.status.addListener(_onSyncStatusChanged);
    unawaited(_open());
  }

  @override
  void dispose() {
    widget.syncService.status.removeListener(_onSyncStatusChanged);
    super.dispose();
  }

  void _onSyncStatusChanged() {
    final completed = widget.syncService.status.value.lastSyncAt;
    if (completed == null || completed == _lastRenderedSync) return;
    _lastRenderedSync = completed;
    unawaited(_controller?.runJavaScript('window.salonNativeRefresh?.()'));
    unawaited(_controller?.runJavaScript('window.salonNativeSyncStatus?.()'));
  }

  Future<void> _handleNativeMessage(JavaScriptMessage message) async {
    final request = jsonDecode(message.message) as Map<String, dynamic>;
    final id = request['id'];
    Map<String, Object?> reply;
    try {
      final result = await PwaBridge(widget.syncService).handle(
        request['action'] as String,
        Map<String, dynamic>.from(request['data'] as Map? ?? {}),
      );
      reply = {'id': id, 'result': result};
    } catch (error) {
      reply = {'id': id, 'error': error.toString().replaceFirst('Bad state: ', '')};
    }
    await _controller?.runJavaScript('window.salonNativeResolve?.(${jsonEncode(reply)})');
  }

  Future<void> _setWebSession() async {
    final cookie = await widget.apiClient.sessionCookie();
    final token = cookie?.split(';').first.replaceFirst('token=', '');
    if (token == null || token.isEmpty) {
      throw StateError('Мобільну сесію не знайдено.');
    }
    await _cookies.setCookie(WebViewCookie(
      name: 'token',
      value: token,
      domain: Uri.parse(ApiClient.baseUrl).host,
      path: '/',
    ));
  }

  Future<void> _open() async {
    try {
      await _setWebSession();
      final controller = WebViewController()
        ..setJavaScriptMode(JavaScriptMode.unrestricted)
        ..setBackgroundColor(const Color(0xFF121214))
        ..addJavaScriptChannel('SalonNative', onMessageReceived: (message) {
          unawaited(_handleNativeMessage(message));
        })
        ..setNavigationDelegate(NavigationDelegate(
          onNavigationRequest: (request) {
            if (Uri.tryParse(request.url)?.path == '/login') {
              unawaited(_refreshSession());
              return NavigationDecision.prevent;
            }
            return NavigationDecision.navigate;
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _loading = false);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame == true && mounted) {
              setState(() {
                _loading = false;
                _error = 'Не вдалося відкрити календар. Перевірте зв’язок і повторіть.';
              });
            }
          },
        ));
      if (!mounted) return;
      setState(() {
        _controller = controller;
        _error = null;
      });
      await controller.loadRequest(Uri.parse('${ApiClient.baseUrl}/master'));
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Не вдалося відкрити календар. Перевірте зв’язок і повторіть.';
        });
      }
    }
  }

  Future<void> _refreshSession() async {
    if (_refreshingSession) return;
    _refreshingSession = true;
    try {
      await widget.apiClient.openMobileSession();
      await _setWebSession();
      await _controller?.loadRequest(Uri.parse('${ApiClient.baseUrl}/master'));
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Сесію не вдалося поновити. Повторіть спробу.');
      }
    } finally {
      _refreshingSession = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Stack(children: [
          if (_controller != null) WebViewWidget(controller: _controller!),
          if (_loading) const Center(child: CircularProgressIndicator()),
          if (_error != null)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(_error!, textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: () {
                      setState(() {
                        _error = null;
                        _loading = true;
                      });
                      unawaited(_controller == null ? _open() : _refreshSession());
                    },
                    child: const Text('Повторити'),
                  ),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
