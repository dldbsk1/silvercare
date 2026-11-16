import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/auth/auth_api.dart';
import '../widgets/data_choice_dialog.dart';

/// 탈퇴 뒤 (A-SET-003). 탈퇴 계정은 다른 API 403 → 이 화면만
///
/// - 탈퇴는 즉시 처리 (워커) → 예정일 X, 데이터 처리 안내만
/// - [로그아웃] → 로그인 화면. 처리 끝나기 전 다시 로그인 → 다시 이 화면
/// - 탈퇴 취소 X (정책)
class WithdrawnScreen extends StatefulWidget {
  const WithdrawnScreen({super.key, this.authApi});

  /// 테스트용 교체
  final AuthApi? authApi;

  @override
  State<WithdrawnScreen> createState() => _WithdrawnScreenState();
}

class _WithdrawnScreenState extends State<WithdrawnScreen> {
  late final AuthApi _auth = widget.authApi ?? AuthApi();
  bool _signingOut = false;

  Future<void> _logout() async {
    setState(() => _signingOut = true);
    try {
      await _auth.signOut();
    } finally {
      if (mounted) context.go('/login');
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: AppColors.background,
        body: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(24, 48, 24, 24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        '탈퇴가\n접수됐어요',
                        style: TextStyle(
                          fontSize: 26,
                          fontWeight: FontWeight.w700,
                          height: 1.5,
                          color: AppColors.text,
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        '그동안 함께해 주셔서 고마워요.',
                        style: TextStyle(fontSize: 17, height: 1.6, color: AppColors.text),
                      ),
                      const SizedBox(height: 24),
                      for (final note in withdrawalNotes) DataNote(note),
                      const DataNote('내가 쓴 기록도 지우기로 했다면 가족 공간에서도 함께 삭제돼요.'),
                      const DataNote('처리가 끝나면 같은 계정으로 다시 가입할 수 있어요.'),
                    ],
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                child: FilledButton(
                  onPressed: _signingOut ? null : _logout,
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.primaryGlow,
                    minimumSize: const Size.fromHeight(52),
                    shape: const StadiumBorder(),
                    textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                  child: const Text('로그아웃'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
