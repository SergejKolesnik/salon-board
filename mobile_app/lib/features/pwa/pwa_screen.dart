import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../core/api/api_client.dart';

/// Shows the existing Body Balance PWA inside the Android application.
class PwaScreen extends StatefulWidget {
  const PwaScreen({required this.apiClient, super.key});

  final ApiClient apiClient;

  @override
  State<PwaScreen> createState() => _PwaScreenState();
}

class _PwaScreenState extends State<PwaScreen> {
  final WebViewCookieManager _cookies = WebViewCookieManager();
  WebViewController? _controller;
  String? _error;
  bool _loading = true;
  bool _refreshingSession = false;

  @override
  void initState() {
    super.initState();
    unawaited(_open());
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
      if (mounted) setState(() => _error = 'Сесію не вдалося поновити. Повторіть спробу.');
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
