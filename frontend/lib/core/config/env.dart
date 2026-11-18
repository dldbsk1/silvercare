import 'package:flutter/foundation.dart';

/// 실행 설정 (--dart-define). 키·주소 코드에 직접 X
///
///   flutter run --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_PUBLISHABLE_KEY=...
///   (실제 휴대폰 → --dart-define=API_BASE_URL=http://PC내부IP:8000)
class Env {
  static const _apiBaseUrl = String.fromEnvironment('API_BASE_URL');

  /// 백엔드 주소. 미지정 → 실행 기기 기준 PC 의 8000번
  /// - Android 에뮬레이터: 10.0.2.2 (에뮬레이터 안 → PC)
  /// - Windows · Chrome · iOS 시뮬레이터: 127.0.0.1
  static String get apiBaseUrl {
    if (_apiBaseUrl.isNotEmpty) return _apiBaseUrl;
    final android = !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
    return android ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000';
  }

  static const supabaseUrl = String.fromEnvironment('SUPABASE_URL');

  /// 소셜 로그인 뒤 앱 복귀 주소 (딥링크). 패키지 이름 = 스킴
  /// AndroidManifest · iOS Info.plist · Supabase Redirect URLs 모두 같은 값
  static const authRedirect = 'com.silvercare.silvercare://login-callback';

  /// publishable key만 (secret key 앱에 넣기 X)
  static const supabasePublishableKey =
      String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');

  /// 푸시 (Firebase). Firebase 콘솔 → 프로젝트 설정 → Android 앱 값
  /// 비움 → 푸시 X (앱 안 알림 목록만). 웹 → 항상 푸시 X
  static const firebaseApiKey = String.fromEnvironment('FIREBASE_API_KEY');
  static const firebaseAppId = String.fromEnvironment('FIREBASE_APP_ID');
  static const firebaseSenderId = String.fromEnvironment('FIREBASE_SENDER_ID');
  static const firebaseProjectId = String.fromEnvironment('FIREBASE_PROJECT_ID');

  static bool get firebaseConfigured =>
      firebaseApiKey.isNotEmpty && firebaseAppId.isNotEmpty && firebaseSenderId.isNotEmpty && firebaseProjectId.isNotEmpty;
}
