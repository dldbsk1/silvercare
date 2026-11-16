import 'package:go_router/go_router.dart';

import '../features/family/screens/family_screen.dart';
import '../features/home/screens/home_screen.dart';
import '../features/onboarding/screens/consent_screen.dart';
import '../features/onboarding/screens/email_login_screen.dart';
import '../features/onboarding/screens/init_setup_screen.dart';
import '../features/onboarding/screens/invite_join_screen.dart';
import '../features/onboarding/screens/login_screen.dart';
import '../features/onboarding/screens/phone_screen.dart';
import '../features/onboarding/screens/start_screen.dart';
import '../features/records/screens/record_list_screen.dart';
import '../features/settings/screens/my_info_screen.dart';
import '../features/settings/screens/withdrawn_screen.dart';
import '../shared/widgets/placeholder_screen.dart';
import 'main_shell.dart';

/// 화면 경로 (기능명세서 화면 ID 주석)
///
/// TODO(로그인 연결): redirect에서 GET /v1/auth/me 결과로 분기
///   로그인 X → /login
///   account.status == withdrawn → /withdrawn
///   동의 미완료 → /onboarding/consents → 이름 + 부모님 등록 (/onboarding/setup)
///   전부 완료 → /home
/// 앱마다 새로 (테스트끼리 이동 상태 공유 X)
GoRouter createAppRouter() => GoRouter(
  // 시작: 저장된 로그인 확인 → 시작하기 또는 다음 단계
  initialLocation: '/',
  routes: [
    GoRoute(
      path: '/',
      builder: (context, state) => const StartScreen(),
    ),
    GoRoute(
      path: '/login', // SCR_A_000
      builder: (context, state) => const LoginScreen(),
    ),
    GoRoute(
      path: '/login/email', // 개발용
      builder: (context, state) => const EmailLoginScreen(),
    ),
    GoRoute(
      path: '/onboarding/phone',
      builder: (context, state) => const PhoneScreen(),
    ),
    GoRoute(
      path: '/onboarding/consents',
      builder: (context, state) => const ConsentScreen(),
    ),
    GoRoute(
      path: '/onboarding/setup', // 이름 + 부모님 등록 (A-ON-003)
      builder: (context, state) => const InitSetupScreen(),
    ),
    GoRoute(
      path: '/onboarding/invite', // 초대 수락 (A-FAM-001)
      builder: (context, state) => const InviteJoinScreen(),
    ),
    GoRoute(
      path: '/withdrawn',
      builder: (context, state) => const WithdrawnScreen(),
    ),
    StatefulShellRoute.indexedStack(
      builder: (context, state, shell) => MainShell(shell: shell),
      branches: [
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/home', // SCR_A_100
              builder: (context, state) => const HomeScreen(),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/records', // SCR_A_200
              builder: (context, state) => const RecordListScreen(),
            ),
          ],
        ),
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/family', // SCR_A_300
              builder: (context, state) => const FamilyScreen(),
            ),
          ],
        ),
        _tab('/survey', '조사 준비'), // SCR_A_400
        StatefulShellBranch(
          routes: [
            GoRoute(
              path: '/settings', // SCR_A_500
              builder: (context, state) => const MyInfoScreen(),
            ),
          ],
        ),
      ],
    ),
  ],
);

StatefulShellBranch _tab(String path, String title) => StatefulShellBranch(
      routes: [
        GoRoute(
          path: path,
          builder: (context, state) => PlaceholderScreen(title: title),
        ),
      ],
    );
