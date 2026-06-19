import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiClient {
  ApiClient()
      : _dio = Dio(
          BaseOptions(
            baseUrl: const String.fromEnvironment(
              'API_BASE_URL',
              defaultValue: 'https://salon-board.onrender.com',
            ),
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

  Future<void> login({required String password, int? masterId}) async {
    await _dio.post<Map<String, dynamic>>(
      '/api/login',
      data: {
        'password': password,
        if (masterId != null) 'master_id': masterId,
      },
    );
  }

  Future<Map<String, dynamic>> bootstrap() async {
    final response = await _dio.get<Map<String, dynamic>>('/api/sync/bootstrap');
    return response.data ?? <String, dynamic>{};
  }

  Future<bool> hasSession() async {
    final cookie = await _loadCookie();
    return cookie != null && cookie.isNotEmpty;
  }

  Future<void> logout() async {
    try {
      await _dio.post<void>('/api/logout');
    } finally {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_sessionCookieKey);
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
