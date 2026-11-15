/// 백엔드 공통 오류 형식 {"error": {"code", "message", "details"}}
class ApiException implements Exception {
  ApiException({
    required this.statusCode,
    required this.code,
    required this.message,
    this.details,
  });

  final int statusCode;

  /// 예: CONSENT_REQUIRED, ACCOUNT_WITHDRAWN, LAST_ADMIN
  final String code;

  /// 사용자에게 그대로 보여도 되는 문구
  final String message;
  final Object? details;

  @override
  String toString() => 'ApiException($statusCode $code)';
}
