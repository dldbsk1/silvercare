import 'dart:async';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'app/router.dart';
import 'app/theme.dart';
import 'core/config/env.dart';
import 'core/push/push_service.dart';
import 'features/notifications/notification_api.dart';
import 'features/notifications/notification_routes.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 설정 없으면 로그인 없이 화면만 확인 (Figma 화면 붙이는 단계)
  if (Env.supabaseUrl.isNotEmpty) {
    await Supabase.initialize(
      url: Env.supabaseUrl,
      publishableKey: Env.supabasePublishableKey,
    );
  }

  runApp(const SilverCareApp());
}

class SilverCareApp extends StatefulWidget {
  const SilverCareApp({super.key});

  @override
  State<SilverCareApp> createState() => _SilverCareAppState();
}

class _SilverCareAppState extends State<SilverCareApp> {
  // 첫 화면: 라우터 initialLocation (/ → 로그인 확인 → 시작하기 또는 다음 단계)
  late final _router = createAppRouter();
  StreamSubscription<Map<String, dynamic>>? _pushOpened;

  @override
  void initState() {
    super.initState();
    _pushOpened = PushService.instance.opened.listen(_openPush);
  }

  @override
  void dispose() {
    _pushOpened?.cancel();
    _router.dispose();
    super.dispose();
  }

  /// 푸시 알림 누름 → 읽음 + 해당 화면 (data: notification_id · type · parent_id · payload 값)
  void _openPush(Map<String, dynamic> data) {
    final id = data['notification_id'];
    if (id is String) unawaited(NotificationApi().markRead(id).catchError((Object _) {}));
    final context = _router.routerDelegate.navigatorKey.currentState?.overlay?.context;
    final type = data['type'];
    if (context == null || type is! String) return;
    openNotificationTarget(context, type: type, parentId: data['parent_id'] as String?, payload: data);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'DAMA',
      theme: AppTheme.light(),
      routerConfig: _router,
      debugShowCheckedModeBanner: false,
    );
  }
}
