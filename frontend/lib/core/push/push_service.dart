import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../features/notifications/notification_api.dart';
import '../config/env.dart';

/// 푸시 알림 (FCM). Android·iOS 앱만 (웹 X)
///
/// - 등록: 홈 진입 (가입 끝난 뒤) → 알림 권한 → 토큰 → POST /devices. 토큰 바뀜 → 다시 등록
/// - 해제: 로그아웃 전 → DELETE /devices/{id} + 토큰 폐기
/// - 알림 누름 (앱 닫힘·백그라운드) → [opened] (앱이 화면 이동)
/// - 앱 켜진 중 도착 → [received] (홈 종 아이콘 새로고침). 시스템 알림은 안 뜸
/// - Firebase 설정 (--dart-define FIREBASE_*) 없음 → 아무것도 안 함
/// - 토큰 API (getToken·onTokenRefresh·deleteToken): 17.x deprecated, 서버 FCM v1 `message.token` 발송과 맞춤
///   새 register()/onRegistered 는 설치 ID(FID) 방식 → 서버 발송 방식 같이 바꿀 때 교체
// ignore_for_file: deprecated_member_use
class PushService {
  PushService._();

  static final instance = PushService._();

  static const _deviceKey = 'push_device_id';
  final _storage = const FlutterSecureStorage();
  final _api = NotificationApi();

  final _opened = StreamController<Map<String, dynamic>>.broadcast();
  final _received = StreamController<void>.broadcast();

  bool _initialized = false;
  bool _registering = false;
  StreamSubscription<String>? _refresh;

  Stream<Map<String, dynamic>> get opened => _opened.stream;
  Stream<void> get received => _received.stream;

  static bool get supported =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS) &&
      Env.firebaseConfigured;

  static String get _platform => defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';

  Future<bool> _init() async {
    if (!supported) return false;
    if (_initialized) return true;
    await Firebase.initializeApp(
      options: const FirebaseOptions(
        apiKey: Env.firebaseApiKey,
        appId: Env.firebaseAppId,
        messagingSenderId: Env.firebaseSenderId,
        projectId: Env.firebaseProjectId,
      ),
    );
    FirebaseMessaging.onMessageOpenedApp.listen((message) => _opened.add(message.data));
    FirebaseMessaging.onMessage.listen((_) => _received.add(null));
    _initialized = true;

    // 앱 꺼진 상태에서 알림 눌러 실행
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) _opened.add(initial.data);
    return true;
  }

  /// 홈 진입 때. 실패해도 앱 사용엔 영향 X (다음 진입 때 다시)
  Future<void> register() async {
    if (_registering) return;
    _registering = true;
    try {
      if (!await _init()) return;
      final messaging = FirebaseMessaging.instance;
      final permission = await messaging.requestPermission();
      if (permission.authorizationStatus == AuthorizationStatus.denied) return;
      final token = await messaging.getToken();
      if (token == null) return;
      await _send(token);
      _refresh ??= messaging.onTokenRefresh.listen((t) => unawaited(_send(t).catchError((Object _) {})));
    } catch (e) {
      debugPrint('푸시 등록 실패: $e');
    } finally {
      _registering = false;
    }
  }

  Future<void> _send(String token) async {
    final deviceId = await _api.registerDevice(platform: _platform, token: token);
    await _storage.write(key: _deviceKey, value: deviceId);
  }

  /// 로그아웃 전. 실패해도 로그아웃은 계속 (서버: 다음 발송 때 무효 토큰 → 기기 끔)
  Future<void> unregister() async {
    if (!supported) return;
    try {
      final deviceId = await _storage.read(key: _deviceKey);
      if (deviceId != null) {
        await _api.deleteDevice(deviceId);
        await _storage.delete(key: _deviceKey);
      }
      if (_initialized) {
        await _refresh?.cancel();
        _refresh = null;
        await FirebaseMessaging.instance.deleteToken();
      }
    } catch (e) {
      debugPrint('푸시 해제 실패: $e');
    }
  }
}
