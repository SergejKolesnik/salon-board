import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiClient {
  static const baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://salon-board.onrender.com',
  );

  ApiClient()
      : _dio = Dio(
          BaseOptions(
            baseUrl: baseUrl,
            connectTimeout: const Duration(seconds: 12),
            receiveTimeout: const Duration(seconds: 20),
            headers: const {'Content-Type': 'application/json'},
          ),
        ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final cookie = await _loadCookie();
          if (cookie != null && cookie.isNotEmpty) {
            options.headers['Cookie'] = cookie;
          }
          handler.next(options);
        },
        onResponse: (response, handler) async {
          final setCookie = response.headers.value('set-cookie');
          if (setCookie != null && setCookie.isNotEmpty) {
            await _saveSessionCookie(setCookie);
          }
          handler.next(response);
        },
      ),
    );
  }

  final Dio _dio;

  Future<Map<String, dynamic>> login(
      {required String password, int? masterId}) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/login',
      data: {
        'password': password,
        if (masterId != null) 'master_id': masterId,
      },
    );
    return response.data ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> openMobileSession() async {
    // Render may need to start the server after an idle period.
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/session',
      options: Options(receiveTimeout: const Duration(seconds: 60)),
    );
    return response.data ?? <String, dynamic>{};
  }

  Future<List<dynamic>> masters() async {
    final response = await _dio.get<List<dynamic>>('/api/masters');
    return response.data ?? const [];
  }

  Future<Map<String, dynamic>> currentUser() async {
    final response = await _dio.get<Map<String, dynamic>>('/api/me');
    return response.data ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> bootstrap() async {
    final response =
        await _dio.get<Map<String, dynamic>>('/api/sync/bootstrap');
    return response.data ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> pull(String since) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/api/sync/pull',
      queryParameters: {'since': since},
    );
    return response.data ?? <String, dynamic>{};
  }

  Future<Map<String, dynamic>> push(List<Map<String, Object?>> pending) async {
    final payload = <String, List<Map<String, Object?>>>{
      'clients': [],
      'appointments': [],
      'breaks': [],
    };
    for (final item in pending) {
      final type = item['entity_type']?.toString();
      if (type == null || !payload.containsKey(type)) continue;
      final data = jsonDecode(item['data_json']?.toString() ?? '{}');
      payload[type]!.add({
        'local_id': item['local_id'],
        'server_id': item['server_id'],
        'action': item['action'],
        'mutation_id': item['mutation_id'],
        'data': data is Map ? data : <String, Object?>{},
      });
    }
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/sync/push',
      data: payload,
    );
    return response.data ?? <String, dynamic>{};
  }

  Future<bool> hasSession() async {
    final cookie = await _loadCookie();
    return cookie != null && cookie.isNotEmpty;
  }

  /// Return the mobile session cookie for the embedded PWA.
  Future<String?> sessionCookie() => _loadCookie();

  Future<void> logout() async {
    final cookie = await _loadCookie();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_sessionCookieKey);
    if (cookie != null && cookie.isNotEmpty) {
      unawaited(
        _dio
            .post<void>('/api/logout',
                options: Options(headers: {'Cookie': cookie}))
            .then<void>((_) {}, onError: (Object _) {}),
      );
    }
  }

  Future<String?> _loadCookie() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_sessionCookieKey);
  }

  Future<void> _saveSessionCookie(String rawCookie) async {
    final token = rawCookie
        .split(',')
        .map((part) => part.trim())
        .firstWhere((part) => part.startsWith('token='), orElse: () => '');
    if (token.isEmpty) return;

    final cookieValue = token.split(';').first;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_sessionCookieKey, cookieValue);
  }

  static const _sessionCookieKey = 'session_cookie';
}
