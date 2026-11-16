import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:silvercare/core/api/api_exception.dart';
import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/family/invite_api.dart';
import 'package:silvercare/features/onboarding/screens/invite_join_screen.dart';
import 'package:silvercare/features/onboarding/setup_api.dart';

const token = 'K7QM-4XPA';
const legacyToken = 'AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde';

InvitePreview samplePreview({bool alreadyMember = false, String docVersion = 'share-v1'}) => InvitePreview(
      inviterName: '김가족',
      parentNickname: '엄마',
      role: 'writer',
      expiresAt: DateTime(2026, 11, 23),
      alreadyMember: alreadyMember,
      shareDocument: ShareDocument(version: docVersion, title: '가족 공유 동의', content: '기록을 가족과 함께 봐요.'),
    );

/// 서버 대신: 미리보기·수락 기록
class FakeInviteApi extends InviteApi {
  FakeInviteApi({this.previews, this.acceptError});

  /// 차례대로 돌려줌 (마지막 것 반복)
  List<InvitePreview>? previews;
  ApiException? previewError;
  ApiException? acceptError;
  final previewed = <String>[];
  final accepted = <(String, String)>[];

  @override
  Future<InvitePreview> preview(String token) async {
    previewed.add(token);
    if (previewError != null) throw previewError!;
    final list = previews ?? [samplePreview()];
    return list[(previewed.length - 1).clamp(0, list.length - 1)];
  }

  @override
  Future<String> accept(String token, String shareDocVersion) async {
    accepted.add((token, shareDocVersion));
    final error = acceptError;
    if (error != null) {
      acceptError = null;
      throw error;
    }
    return 'p1';
  }
}

class FakeSetupApi extends SetupApi {
  final names = <String>[];

  @override
  Future<void> updateName(String displayName) async => names.add(displayName);
}

class FakeAuthApi extends AuthApi {
  FakeAuthApi({this.savedName, this.invite});

  String? savedName;
  FakeInviteApi? invite;

  @override
  Future<Me> fetchMe() async => Me(
        userId: 'u1',
        displayName: savedName,
        withdrawn: false,
        consentsCompleted: true,
        nameSet: savedName != null,
        parentRegistered: invite?.accepted.isNotEmpty ?? false,
        parentIds: const [],
      );
}

Widget app(FakeInviteApi invite, FakeSetupApi setup, FakeAuthApi auth) {
  final router = GoRouter(
    initialLocation: '/invite',
    routes: [
      GoRoute(
        path: '/invite',
        builder: (_, _) => InviteJoinScreen(inviteApi: invite, setupApi: setup, authApi: auth),
      ),
      GoRoute(path: '/onboarding/setup', builder: (_, _) => const Text('첫 설정')),
      GoRoute(path: '/home', builder: (_, _) => const Text('홈 화면')),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

FilledButton bottomButton(WidgetTester tester, String label) =>
    tester.widget<FilledButton>(find.widgetWithText(FilledButton, label));

Future<void> enterLink(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField).first, text);
  await tester.pump();
  await tester.tap(find.text('확인'));
  await tester.pumpAndSettle();
}

Future<void> agree(WidgetTester tester) async {
  await tester.ensureVisible(find.text('위 내용을 읽고 동의해요'));
  await tester.tap(find.text('위 내용을 읽고 동의해요'));
  await tester.pump();
}

void main() {
  group('parseInviteToken', () {
    test('코드만 · 공유 문구 통째 · 대소문자·공백·하이픈', () {
      expect(parseInviteToken('K7QM-4XPA'), 'K7QM-4XPA');
      expect(parseInviteToken(' k7qm-4xpa '), 'K7QM-4XPA');
      expect(parseInviteToken('k7qm 4xpa'), 'K7QM-4XPA');
      expect(parseInviteToken('K7QM4XPA'), 'K7QM-4XPA');
      expect(
        parseInviteToken('엄마 기록을 함께 남겨요. DAMA 초대 코드 (7일)\nK7QM-4XPA\nDAMA 앱 첫 화면 [초대 코드 입력]에 이 메시지를 붙여넣어 주세요.'),
        'K7QM-4XPA',
      );
    });

    test('링크 · 예전 43자 토큰', () {
      expect(parseInviteToken('https://dama.app/invite#t=K7QM4XPA'), 'K7QM4XPA');
      expect(parseInviteToken('https://dama.app/invite?t=$legacyToken&x=1'), legacyToken);
      expect(parseInviteToken('초대 링크\nhttps://dama.app/invite#t=$legacyToken\n앱에서 붙여넣어 주세요.'), legacyToken);
      expect(parseInviteToken('  $legacyToken \n'), legacyToken);
    });

    test('코드 없음 → null', () {
      expect(parseInviteToken(''), isNull);
      expect(parseInviteToken('안녕하세요'), isNull);
      expect(parseInviteToken('K7QM-4XP'), isNull);
      expect(parseInviteToken('https://dama.app/invite'), isNull);
      expect(parseInviteToken('https://dama.app/invite#t=short'), isNull);
    });
  });

  testWidgets('링크 확인 → 동의 → 수락 → 다음 단계', (tester) async {
    final invite = FakeInviteApi();
    final setup = FakeSetupApi();
    final auth = FakeAuthApi(savedName: '나', invite: invite);
    await tester.pumpWidget(app(invite, setup, auth));
    await tester.pumpAndSettle();

    expect(bottomButton(tester, '확인').onPressed, isNull);
    await enterLink(tester, '초대 링크\nhttps://dama.app/invite#t=$token');

    expect(invite.previewed, [token]);
    expect(find.textContaining('김가족님이'), findsOneWidget);
    expect(find.text('기록하고 볼 수 있어요'), findsOneWidget);
    expect(find.text('11월 23일까지'), findsOneWidget);
    // 이름 이미 있음 → 이름 칸 X
    expect(find.text('내 이름'), findsNothing);

    expect(bottomButton(tester, '함께 기록하기').onPressed, isNull);
    await agree(tester);
    await tester.tap(find.text('함께 기록하기'));
    await tester.pumpAndSettle();

    expect(invite.accepted, [(token, 'share-v1')]);
    expect(setup.names, isEmpty);
    expect(find.text('홈 화면'), findsOneWidget);
  });

  testWidgets('이름 없음 → 이름 입력 필수, 수락 전에 저장', (tester) async {
    final invite = FakeInviteApi();
    final setup = FakeSetupApi();
    final auth = FakeAuthApi(invite: invite);
    await tester.pumpWidget(app(invite, setup, auth));
    await tester.pumpAndSettle();

    await enterLink(tester, token);
    expect(find.text('내 이름'), findsOneWidget);

    await agree(tester);
    expect(bottomButton(tester, '함께 기록하기').onPressed, isNull);

    await tester.enterText(find.byType(TextField).first, ' 홍길동 ');
    await tester.pump();
    // 다음 단계 판단에 이름 반영
    auth.savedName = '홍길동';
    await tester.tap(find.text('함께 기록하기'));
    await tester.pumpAndSettle();

    expect(setup.names, ['홍길동']);
    expect(invite.accepted, hasLength(1));
    expect(find.text('홈 화면'), findsOneWidget);
  });

  testWidgets('링크 못 찾음 → 안내, 서버 호출 X', (tester) async {
    final invite = FakeInviteApi();
    await tester.pumpWidget(app(invite, FakeSetupApi(), FakeAuthApi(savedName: '나')));
    await tester.pumpAndSettle();

    await enterLink(tester, '안녕하세요');
    expect(find.textContaining('초대 코드를 찾지 못했어요'), findsOneWidget);
    expect(invite.previewed, isEmpty);
  });

  testWidgets('만료된 초대 → 서버 문구', (tester) async {
    final invite = FakeInviteApi()
      ..previewError = ApiException(statusCode: 410, code: 'INVITE_EXPIRED', message: '기간이 지난 초대예요.');
    await tester.pumpWidget(app(invite, FakeSetupApi(), FakeAuthApi(savedName: '나')));
    await tester.pumpAndSettle();

    await enterLink(tester, token);
    expect(find.text('기간이 지난 초대예요.'), findsOneWidget);
    expect(find.text('확인'), findsOneWidget);
  });

  testWidgets('수락 중 초대 사용됨 → 1단계로', (tester) async {
    final invite = FakeInviteApi(
      acceptError: ApiException(statusCode: 409, code: 'INVITE_USED', message: '이미 사용된 초대예요.'),
    );
    await tester.pumpWidget(app(invite, FakeSetupApi(), FakeAuthApi(savedName: '나', invite: invite)));
    await tester.pumpAndSettle();

    await enterLink(tester, token);
    await agree(tester);
    await tester.tap(find.text('함께 기록하기'));
    await tester.pumpAndSettle();

    expect(find.text('이미 사용된 초대예요.'), findsOneWidget);
    expect(find.text('확인'), findsOneWidget);
    expect(find.text('홈 화면'), findsNothing);
  });

  testWidgets('동의 문서 바뀜 → 새 문서로 다시 동의', (tester) async {
    final invite = FakeInviteApi(
      previews: [samplePreview(), samplePreview(docVersion: 'share-v2')],
      acceptError: ApiException(statusCode: 400, code: 'CONSENT_REQUIRED', message: '동의 문구가 바뀌었어요.'),
    );
    await tester.pumpWidget(app(invite, FakeSetupApi(), FakeAuthApi(savedName: '나', invite: invite)));
    await tester.pumpAndSettle();

    await enterLink(tester, token);
    await agree(tester);
    await tester.tap(find.text('함께 기록하기'));
    await tester.pumpAndSettle();

    expect(find.text('동의 문구가 바뀌었어요.'), findsOneWidget);
    expect(bottomButton(tester, '함께 기록하기').onPressed, isNull);

    await agree(tester);
    await tester.tap(find.text('함께 기록하기'));
    await tester.pumpAndSettle();

    expect(invite.accepted.map((a) => a.$2), ['share-v1', 'share-v2']);
    expect(find.text('홈 화면'), findsOneWidget);
  });

  testWidgets('이미 가족 → 홈으로', (tester) async {
    final invite = FakeInviteApi(previews: [samplePreview(alreadyMember: true)]);
    await tester.pumpWidget(app(invite, FakeSetupApi(), FakeAuthApi(savedName: '나')));
    await tester.pumpAndSettle();

    await enterLink(tester, token);
    expect(find.text('이미 함께 기록하고 있어요.'), findsOneWidget);
    expect(find.text('위 내용을 읽고 동의해요'), findsNothing);

    await tester.tap(find.text('홈으로'));
    await tester.pumpAndSettle();
    expect(invite.accepted, isEmpty);
    // 가족 X 로 나오는 가짜 → 첫 설정으로
    expect(find.text('첫 설정'), findsOneWidget);
  });

  testWidgets('확인 단계에서 뒤로 → 붙여넣기 단계', (tester) async {
    final invite = FakeInviteApi();
    await tester.pumpWidget(app(invite, FakeSetupApi(), FakeAuthApi(savedName: '나')));
    await tester.pumpAndSettle();

    await enterLink(tester, token);
    await tester.tap(find.byTooltip('뒤로'));
    await tester.pumpAndSettle();

    expect(find.text('확인'), findsOneWidget);
    expect(find.text(token), findsOneWidget);
  });
}
