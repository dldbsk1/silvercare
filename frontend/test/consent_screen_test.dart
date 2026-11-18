import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/onboarding/consent_api.dart';
import 'package:silvercare/features/onboarding/screens/consent_screen.dart';

ConsentDocument doc(String type, {bool required = true}) => ConsentDocument(
      type: type,
      required: required,
      docVersion: 'v1',
      title: '서버 제목 $type',
      content: '$type 문구 전체',
    );

/// 서버 대신: 문서 목록 + 저장 내용 기록
class FakeConsentApi extends ConsentApi {
  Set<String>? savedAgreed;

  @override
  Future<List<ConsentDocument>> fetchRequired() async =>
      [doc('noti', required: false), doc('health'), doc('service'), doc('privacy')];

  @override
  Future<void> save(List<ConsentDocument> documents, Set<String> agreed) async =>
      savedAgreed = Set.of(agreed);
}

class FakeAuthApi extends AuthApi {
  @override
  Future<Me> fetchMe() async => Me(
        userId: 'u1',
        withdrawn: false,
        consentsCompleted: true,
        nameSet: false,
        parentRegistered: false,
        parentIds: const [],
      );
}

Widget app(FakeConsentApi api) {
  final router = GoRouter(
    initialLocation: '/consents',
    routes: [
      GoRoute(
        path: '/consents',
        builder: (_, _) => ConsentScreen(consentApi: api, authApi: FakeAuthApi()),
      ),
      GoRoute(path: '/onboarding/setup', builder: (_, _) => const Text('이름 화면')),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

FilledButton nextButton(WidgetTester tester) =>
    tester.widget<FilledButton>(find.widgetWithText(FilledButton, '다음'));

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('화면 순서·문구 (Figma) + 필수만 체크하면 다음 → 이름 화면', (tester) async {
    final api = FakeConsentApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    // 서버 순서와 무관하게 서비스 → 개인정보 → 건강정보 → 알림
    final service = tester.getTopLeft(find.text('[필수] 서비스 이용 동의', findRichText: true)).dy;
    final health = tester.getTopLeft(find.text('[필수] 건강정보 수집·이용 동의', findRichText: true)).dy;
    final noti = tester.getTopLeft(find.text('[선택] 알림 수신 동의', findRichText: true)).dy;
    expect(service < health && health < noti, isTrue);

    expect(nextButton(tester).onPressed, isNull);

    await tester.tap(find.text('[필수] 서비스 이용 동의', findRichText: true));
    await tester.tap(find.text('[필수] 개인정보 수집·이용 동의', findRichText: true));
    await tester.tap(find.text('[필수] 건강정보 수집·이용 동의', findRichText: true));
    await tester.pump();
    expect(nextButton(tester).onPressed, isNotNull);

    await tester.tap(find.text('다음'));
    await tester.pumpAndSettle();
    expect(api.savedAgreed, {'service', 'privacy', 'health'});
    expect(find.text('이름 화면'), findsOneWidget);
  });

  testWidgets('전체 동의 → 선택 포함 전부, 다시 누르면 전부 해제', (tester) async {
    final api = FakeConsentApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('전체 동의'));
    await tester.pump();
    await tester.tap(find.text('다음'));
    await tester.pumpAndSettle();
    expect(api.savedAgreed, {'service', 'privacy', 'health', 'noti'});
  });

  testWidgets('보기 → 서버 문구 전체', (tester) async {
    await tester.pumpWidget(app(FakeConsentApi()));
    await tester.pumpAndSettle();

    await tester.tap(find.text('보기').first);
    await tester.pumpAndSettle();
    expect(find.text('service 문구 전체'), findsOneWidget);
  });

  testWidgets('발행된 문구 없음 → 전체 동의 X, 준비 중 안내 + 다시 불러오기', (tester) async {
    await tester.pumpWidget(app(EmptyConsentApi()));
    await tester.pumpAndSettle();

    expect(find.text('전체 동의'), findsNothing);
    expect(find.text('동의 문구를 준비하고 있어요. 잠시 후 다시 시도해 주세요.'), findsOneWidget);
    expect(find.text('다시 불러오기'), findsOneWidget);
  });
}

class EmptyConsentApi extends FakeConsentApi {
  @override
  Future<List<ConsentDocument>> fetchRequired() async => [];
}
