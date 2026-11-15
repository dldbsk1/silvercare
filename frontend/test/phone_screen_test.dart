import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/api/api_exception.dart';
import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/onboarding/screens/phone_screen.dart';

/// 실제 Supabase·백엔드 대신 (보낸 번호·코드 기록)
class FakeAuthApi extends AuthApi {
  String? sentTo;
  String? verifiedCode;
  bool wrongCode = false;

  @override
  Future<void> sendPhoneOtp(String phone) async => sentTo = phone;

  @override
  Future<void> verifyPhoneOtp(String phone, String code) async {
    if (wrongCode) {
      throw ApiException(statusCode: 403, code: 'otp_expired', message: '인증번호가 맞지 않아요.');
    }
    verifiedCode = code;
  }

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

Widget app(FakeAuthApi api) {
  final router = GoRouter(
    initialLocation: '/phone',
    routes: [
      GoRoute(path: '/phone', builder: (_, _) => PhoneScreen(authApi: api)),
      GoRoute(path: '/onboarding/consents', builder: (_, _) => const Text('동의 화면')),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('번호 → 인증번호 받기 → 6자리 → 다음 단계 (동의)', (tester) async {
    final api = FakeAuthApi();
    await tester.pumpWidget(app(api));

    // 번호 완성 전에는 받기 비활성
    await tester.enterText(find.byType(TextField).first, '0101234');
    await tester.pump();
    expect(tester.widget<TextButton>(find.byType(TextButton)).onPressed, isNull);

    await tester.enterText(find.byType(TextField).first, '01012345678');
    await tester.pump();
    expect(find.text('010-1234-5678'), findsOneWidget);

    await tester.tap(find.text('인증번호 받기'));
    await tester.pump();
    expect(api.sentTo, '+821012345678');
    expect(find.text('인증번호를 보냈어요 (3:00)'), findsOneWidget);

    // 6자리 입력 → 자동 제출 → /auth/me 결과로 이동
    await tester.enterText(find.byType(TextField).last, '482913');
    await tester.pumpAndSettle();
    expect(api.verifiedCode, '482913');
    expect(find.text('동의 화면'), findsOneWidget);
  });

  testWidgets('틀린 인증번호 → 안내 + 입력 비움', (tester) async {
    final api = FakeAuthApi()..wrongCode = true;
    await tester.pumpWidget(app(api));

    await tester.enterText(find.byType(TextField).first, '01012345678');
    await tester.pump();
    await tester.tap(find.text('인증번호 받기'));
    await tester.pump();

    await tester.enterText(find.byType(TextField).last, '111111');
    await tester.pump();
    await tester.pump();
    expect(find.text('인증번호가 맞지 않아요.'), findsOneWidget);
    expect(find.text('동의 화면'), findsNothing);

    // 타이머 정리
    await tester.pumpWidget(const SizedBox());
  });
}
