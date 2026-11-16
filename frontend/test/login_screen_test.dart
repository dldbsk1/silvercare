import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:silvercare/core/api/api_exception.dart';
import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/onboarding/screens/login_screen.dart';

/// Supabase 대신: 카카오 화면 열기 기록 + 로그인 완료 이벤트 직접 보냄
class FakeAuthApi extends AuthApi {
  FakeAuthApi({this.launchError, this.opens = true});

  final ApiException? launchError;
  final bool opens;
  final events = StreamController<void>.broadcast();
  int kakaoCalls = 0;

  @override
  Future<bool> signInWithKakao() async {
    kakaoCalls++;
    if (launchError != null) throw launchError!;
    return opens;
  }

  @override
  Stream<void> get signedIn => events.stream;

  @override
  Future<Me> fetchMe() async => Me(
        userId: 'u1',
        withdrawn: false,
        consentsCompleted: false,
        nameSet: false,
        parentRegistered: false,
        parentIds: const [],
      );
}

Widget app(FakeAuthApi auth) {
  final router = GoRouter(
    initialLocation: '/login',
    routes: [
      GoRoute(path: '/login', builder: (_, _) => LoginScreen(authApi: auth)),
      GoRoute(path: '/onboarding/consents', builder: (_, _) => const Text('동의 화면')),
      GoRoute(path: '/onboarding/phone', builder: (_, _) => const Text('휴대폰 화면')),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

void main() {
  testWidgets('카카오 → 화면 열기 → 앱 복귀 (로그인 완료) → 다음 단계', (tester) async {
    final auth = FakeAuthApi();
    await tester.pumpWidget(app(auth));

    await tester.tap(find.text('카카오로 시작하기'));
    await tester.pumpAndSettle();
    expect(auth.kakaoCalls, 1);
    expect(find.text('동의 화면'), findsNothing);

    auth.events.add(null);
    await tester.pumpAndSettle();
    expect(find.text('동의 화면'), findsOneWidget);
  });

  testWidgets('카카오 안 누름 → 다른 로그인 완료 이벤트 무시 (휴대폰 화면이 처리)', (tester) async {
    final auth = FakeAuthApi();
    await tester.pumpWidget(app(auth));

    auth.events.add(null);
    await tester.pumpAndSettle();
    expect(find.text('동의 화면'), findsNothing);
    expect(find.text('카카오로 시작하기'), findsOneWidget);
  });

  testWidgets('카카오 실패 (복귀 오류) → 안내', (tester) async {
    final auth = FakeAuthApi();
    await tester.pumpWidget(app(auth));

    await tester.tap(find.text('카카오로 시작하기'));
    await tester.pumpAndSettle();
    auth.events.addError(ApiException(statusCode: 400, code: 'access_denied', message: '카카오 로그인을 하지 못했어요.'));
    await tester.pumpAndSettle();

    expect(find.text('카카오 로그인을 하지 못했어요.'), findsOneWidget);
    expect(find.text('동의 화면'), findsNothing);
  });

  testWidgets('카카오 화면 못 엶 → 안내, 이후 완료 이벤트 무시', (tester) async {
    final auth = FakeAuthApi(
      launchError: ApiException(statusCode: 400, code: 'provider_disabled', message: '지금은 카카오 로그인이 꺼져 있어요.'),
    );
    await tester.pumpWidget(app(auth));

    await tester.tap(find.text('카카오로 시작하기'));
    await tester.pumpAndSettle();
    expect(find.text('지금은 카카오 로그인이 꺼져 있어요.'), findsOneWidget);

    auth.events.add(null);
    await tester.pumpAndSettle();
    expect(find.text('동의 화면'), findsNothing);
  });

  testWidgets('휴대폰 번호 → 휴대폰 화면', (tester) async {
    await tester.pumpWidget(app(FakeAuthApi()));

    await tester.tap(find.text('휴대폰 번호로 시작하기'));
    await tester.pumpAndSettle();
    expect(find.text('휴대폰 화면'), findsOneWidget);
  });
}
