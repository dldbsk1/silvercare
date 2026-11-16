import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/features/settings/screens/withdrawn_screen.dart';

class FakeAuthApi extends AuthApi {
  bool signedOut = false;

  @override
  Future<void> signOut() async => signedOut = true;
}

Widget app(FakeAuthApi auth) {
  final router = GoRouter(
    initialLocation: '/withdrawn',
    routes: [
      GoRoute(path: '/withdrawn', builder: (_, _) => WithdrawnScreen(authApi: auth)),
      GoRoute(path: '/login', builder: (_, _) => const Text('로그인 화면')),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

void main() {
  testWidgets('데이터 처리 안내', (tester) async {
    await tester.pumpWidget(app(FakeAuthApi()));
    await tester.pumpAndSettle();

    expect(find.text('탈퇴가\n접수됐어요'), findsOneWidget);
    expect(find.textContaining('계정 정보는 바로 삭제돼요'), findsOneWidget);
    expect(find.textContaining('\'탈퇴한 사용자\''), findsOneWidget);
  });

  testWidgets('로그아웃 → 로그인 화면', (tester) async {
    final auth = FakeAuthApi();
    await tester.pumpWidget(app(auth));
    await tester.pumpAndSettle();

    await tester.tap(find.text('로그아웃'));
    await tester.pumpAndSettle();

    expect(auth.signedOut, isTrue);
    expect(find.text('로그인 화면'), findsOneWidget);
  });
}
