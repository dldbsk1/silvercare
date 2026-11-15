import 'package:flutter/foundation.dart';
import 'package:dio/dio.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../config/env.dart';
import 'api_exception.dart';

/// 백엔드 호출 공통
/// - 로그인 토큰: Supabase 세션 access token → Authorization: Bearer
/// - 응답: {"data": ...} 의 data만 반환
/// - 오류: ApiException (code로 화면 분기)
class ApiClient {
  ApiClient({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: '${Env.apiBaseUrl}/v1',
              connectTimeout: const Duration(seconds: 10),
              receiveTimeout: const Duration(seconds: 20),
            )) {
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        final token = Supabase.instance.client.auth.currentSession?.accessToken;
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(options);
      },
    ));
  }

  final Dio _dio;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _send(() => _dio.get(path, queryParameters: query));

  /// 목록 응답 전체 ({"data": [...], "meta": {...}}). 커서 목록용
  Future<Map<String, dynamic>> getPage(String path, {Map<String, dynamic>? query}) async {
    try {
      final response = await _dio.get(path, queryParameters: query);
      return Map<String, dynamic>.from(response.data as Map);
    } on DioException catch (e) {
      throw _toApiException(e);
    }
  }

  Future<dynamic> post(String path, {Object? body, Map<String, String>? headers}) =>
      _send(() => _dio.post(path, data: body, options: Options(headers: headers)));

  Future<dynamic> put(String path, {Object? body}) =>
      _send(() => _dio.put(path, data: body));

  Future<dynamic> patch(String path, {Object? body}) =>
      _send(() => _dio.patch(path, data: body));

  Future<void> delete(String path) => _send(() => _dio.delete(path));

  Future<dynamic> _send(Future<Response> Function() request) async {
    try {
      final response = await request();
      final body = response.data;
      return body is Map ? body['data'] : null;
    } on DioException catch (e) {
      throw _toApiException(e);
    }
  }

  ApiException _toApiException(DioException e) {
    final response = e.response;
    final error = response?.data is Map ? response!.data['error'] : null;
    if (error is Map) {
      return ApiException(
        statusCode: response!.statusCode ?? 0,
        code: error['code'] as String? ?? 'UNKNOWN',
        message: error['message'] as String? ?? '잠시 후 다시 시도해 주세요.',
        details: error['details'],
      );
    }
    // 응답은 있는데 우리 서버 형식 X (다른 프로그램이 같은 주소 사용 · 주소 잘못 · 프록시 오류)
    if (response != null) {
      return ApiException(
        statusCode: response.statusCode ?? 0,
        code: 'UNEXPECTED_RESPONSE',
        message: kDebugMode
            ? '서버 주소를 확인해 주세요. (${response.statusCode} ${e.requestOptions.uri})'
            : '잠시 후 다시 시도해 주세요.',
      );
    }
    // 연결 실패·시간 초과 (서버 응답 없음)
    return ApiException(
      statusCode: response?.statusCode ?? 0,
      code: 'NETWORK_ERROR',
      message: '인터넷 연결을 확인해 주세요.',
    );
  }
}
