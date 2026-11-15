import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/onboarding/screens/init_setup_screen.dart';
import 'package:silvercare/features/onboarding/setup_api.dart';

/// 서버 대신: 저장한 이름·부모님·키 기록
class FakeSetupApi extends SetupApi {
  final names = <String>[];
  final parents = <Map<String, dynamic>>[];
  final keys = <String>[];

  @override
  Future<void> updateName(String displayName) async => names.add(displayName);

  @override
  Future<void> createParent(ParentInput input, {required String idempotencyKey}) async {
    parents.add(input.toJson());
    keys.add(idempotencyKey);
  }
}

class FakeAuthApi extends AuthApi {
  FakeAuthApi({this.savedName});

  final String? savedName;
  bool registered = false;

  @override
  Future<Me> fetchMe() async => Me(
        userId: 'u1',
        displayName: savedName,
        withdrawn: false,
        consentsCompleted: true,
        nameSet: savedName != null || registered,
        parentRegistered: registered,
        parentIds: const [],
      );
}

Widget app(FakeSetupApi setup, FakeAuthApi auth) {
  final router = GoRouter(
    initialLocation: '/setup',
    routes: [
      GoRoute(path: '/setup', builder: (_, _) => InitSetupScreen(setupApi: setup, authApi: auth)),
      GoRoute(path: '/onboarding/setup', builder: (_, _) => const Text('설정 다시')),
      GoRoute(path: '/home', builder: (_, _) => const Text('홈 화면')),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

FilledButton startButton(WidgetTester tester) =>
    tester.widget<FilledButton>(find.widgetWithText(FilledButton, '시작하기'));

Future<void> tapText(WidgetTester tester, String text) async {
  await tester.ensureVisible(find.text(text));
  await tester.tap(find.text(text));
  await tester.pump();
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('이름 + 직접입력 호칭 + 선택 → 이름 저장 → 부모님 등록 → 홈', (tester) async {
    final setup = FakeSetupApi();
    final auth = FakeAuthApi();
    await tester.pumpWidget(app(setup, auth));
    await tester.pumpAndSettle();

    expect(startButton(tester).onPressed, isNull);

    await tester.enterText(find.byType(TextField).first, '홍길동');
    await tapText(tester, '직접입력');
    await tester.enterText(find.byType(TextField).last, '외할머니');
    await tapText(tester, '80대');
    await tapText(tester, '조사 대기');
    await tapText(tester, '따로 살아요');
    expect(startButton(tester).onPressed, isNotNull);

    auth.registered = true;
    await tester.tap(find.text('시작하기'));
    await tester.pumpAndSettle();

    expect(setup.names, ['홍길동']);
    expect(setup.parents.single, {
      'nickname': '외할머니',
      'age_band': '80s',
      'apply_stage': 'waiting',
      'cohabiting': false,
    });
    expect(find.text('홈 화면'), findsOneWidget);
  });

  testWidgets('이미 정한 이름 → 미리 채움, 다시 저장 X / 나이대 다시 누르면 해제', (tester) async {
    final setup = FakeSetupApi();
    final auth = FakeAuthApi(savedName: '김철수')..registered = true;
    await tester.pumpWidget(app(setup, auth));
    await tester.pumpAndSettle();

    expect(find.text('김철수'), findsOneWidget);

    await tapText(tester, '엄마');
    await tapText(tester, '70대');
    await tapText(tester, '70대');
    await tapText(tester, '신청 전');
    await tapText(tester, '같이 살아요');
    await tester.tap(find.text('시작하기'));
    await tester.pumpAndSettle();

    expect(setup.names, isEmpty);
    expect(setup.parents.single['age_band'], isNull);
    expect(setup.parents.single['nickname'], '엄마');
    expect(setup.parents.single['cohabiting'], isTrue);
  });
}
