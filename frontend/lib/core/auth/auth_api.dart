import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../config/env.dart';
import 'me.dart';

/// 로그인 (Supabase Auth) + 내 상태 (백엔드 /auth/me)
///
/// 휴대폰 OTP: Supabase 대시보드 Phone 공급자 + SMS 업체 설정 필요
///   개발 중: Auth → Phone → Test phone numbers (실제 문자 X, 정해 둔 번호·코드)
class AuthApi {
  AuthApi({this.client});

  /// 테스트용 교체. 기본: 처음 쓸 때 생성 (Supabase 초기화 뒤)
  ApiClient? client;
  ApiClient get _api => client ??= ApiClient();

  static bool get configured => Env.supabaseUrl.isNotEmpty;

  GoTrueClient get _auth => Supabase.instance.client.auth;

  /// 이메일 로그인 (개발용, 제품 로그인은 카카오·휴대폰)
  Future<void> signInWithEmail(String email, String password) async {
    _ensureConfigured();
    try {
      await _auth.signInWithPassword(email: email, password: password);
    } on AuthException catch (e) {
      throw _emailError(e, switch (e.code) {
        'email_not_confirmed' => '메일함에서 인증 링크를 먼저 눌러 주세요.',
        'invalid_credentials' => '이메일 또는 비밀번호가 맞지 않아요.',
        _ => '로그인하지 못했어요.',
      });
    }
  }

  /// 이메일 가입. 반환: 바로 로그인됨 여부 (Supabase "Confirm email" 켜져 있으면 false → 메일 인증 후 로그인)
  Future<bool> signUpWithEmail(String email, String password) async {
    _ensureConfigured();
    try {
      final response = await _auth.signUp(email: email, password: password);
      return response.session != null;
    } on AuthException catch (e) {
      throw _emailError(e, switch (e.code) {
        'user_already_exists' || 'email_exists' => '이미 가입한 이메일이에요. 로그인해 주세요.',
        'weak_password' => '비밀번호는 6자 이상으로 정해 주세요.',
        'email_address_invalid' => '쓸 수 없는 이메일 주소예요. 다른 주소로 해 주세요.',
        'signup_disabled' || 'email_provider_disabled' => '지금은 이메일 가입이 꺼져 있어요.',
        _ => '가입하지 못했어요.',
      });
    }
  }

  /// 저장된 로그인 세션 있음 (앱 재실행 시 바로 다음 단계로)
  bool get hasSession => configured && _auth.currentSession != null;

  /// 로그인 연락처 (휴대폰 → 가운데 가림 / 이메일). 세션 없음 → null
  String? get contact {
    if (!configured) return null;
    final user = _auth.currentUser;
    final phone = user?.phone;
    if (phone != null && phone.isNotEmpty) return maskPhone(phone);
    return user?.email;
  }

  /// 821012345678 · +82 10-1234-5678 → 010-****-5678
  static String maskPhone(String phone) {
    var digits = phone.replaceAll(RegExp(r'\D'), '');
    if (digits.startsWith('82')) digits = '0${digits.substring(2)}';
    if (digits.length < 8) return phone;
    return '${digits.substring(0, 3)}-****-${digits.substring(digits.length - 4)}';
  }

  Future<void> signOut() async {
    if (configured) await _auth.signOut();
  }

  /// 인증번호 문자 보내기. phone: +821012345678 형식
  Future<void> sendPhoneOtp(String phone) async {
    _ensureConfigured();
    try {
      await _auth.signInWithOtp(phone: phone);
    } on AuthException catch (e) {
      throw _fromAuth(e, sending: true);
    }
  }

  /// 인증번호 확인 → 로그인 세션 저장 (supabase_flutter가 보관·갱신)
  Future<void> verifyPhoneOtp(String phone, String code) async {
    _ensureConfigured();
    try {
      await _auth.verifyOTP(type: OtpType.sms, phone: phone, token: code);
    } on AuthException catch (e) {
      throw _fromAuth(e, sending: false);
    }
  }

  Future<Me> fetchMe() async {
    final data = await _api.get('/auth/me');
    return Me.fromJson(data as Map<String, dynamic>);
  }

  /// 연결 실패 (주소·인터넷) 구분 + 개발 빌드: 원인 코드 덧붙임 (화면에서 바로 확인)
  ApiException _emailError(AuthException e, String message) {
    debugPrint('Supabase Auth 오류: ${e.statusCode} ${e.code} ${e.message}');
    final network = e is AuthRetryableFetchException;
    final text = network ? 'Supabase에 연결하지 못했어요. SUPABASE_URL·인터넷을 확인해 주세요.' : message;
    return ApiException(
      statusCode: int.tryParse(e.statusCode ?? '') ?? 0,
      code: e.code ?? (network ? 'NETWORK_ERROR' : 'AUTH_ERROR'),
      message: kDebugMode ? '$text\n(${e.statusCode ?? '-'} ${e.code ?? ''} ${e.message})' : text,
    );
  }

  void _ensureConfigured() {
    if (!configured) {
      throw ApiException(
        statusCode: 0,
        code: 'NOT_CONFIGURED',
        message: '서버 설정이 없어요. SUPABASE_URL을 넣고 다시 실행해 주세요.',
      );
    }
  }

  ApiException _fromAuth(AuthException e, {required bool sending}) {
    final code = e.code ?? '';
    final String message;
    if (code.contains('rate_limit') || e.statusCode == '429') {
      message = '요청이 많아요. 잠시 후 다시 시도해 주세요.';
    } else if (code == 'otp_expired') {
      message = '인증번호 시간이 지났어요. 다시 받아 주세요.';
    } else if (sending) {
      message = '인증번호를 보내지 못했어요. 번호를 확인해 주세요.';
    } else {
      message = '인증번호가 맞지 않아요.';
    }
    return ApiException(
      statusCode: int.tryParse(e.statusCode ?? '') ?? 0,
      code: code.isEmpty ? 'AUTH_ERROR' : code,
      message: message,
    );
  }
}
