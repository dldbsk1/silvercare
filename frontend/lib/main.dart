import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'app/router.dart';
import 'app/theme.dart';
import 'core/config/env.dart';

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

  @override
  void dispose() {
    _router.dispose();
    super.dispose();
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
