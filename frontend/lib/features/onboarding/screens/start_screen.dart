import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';

/// 앱 시작: 저장된 로그인 있으면 /auth/me → 다음 단계, 없으면 시작하기 화면
///
/// 서버 연결 실패 → 시작하기 화면 (다시 로그인하면 이어짐)
class StartScreen extends StatefulWidget {
  const StartScreen({super.key, this.authApi});

  /// 테스트용 교체
  final AuthApi? authApi;

  @override
  State<StartScreen> createState() => _StartScreenState();
}

class _StartScreenState extends State<StartScreen> {
  late final AuthApi _auth = widget.authApi ?? AuthApi();

  @override
  void initState() {
    super.initState();
    // 첫 화면 그린 뒤 이동 (그리는 중 이동 X)
    WidgetsBinding.instance.addPostFrameCallback((_) => _route());
  }

  Future<void> _route() async {
    var next = '/login';
    if (_auth.hasSession) {
      try {
        next = (await _auth.fetchMe()).nextRoute;
      } on ApiException {
        next = '/login';
      }
    }
    if (mounted) context.go(next);
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.background,
      body: Center(child: CircularProgressIndicator()),
    );
  }
}
