import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/family/family_api.dart';
import 'package:silvercare/features/settings/screens/my_info_screen.dart';
import 'package:silvercare/features/settings/settings_api.dart';

class FakeAuthApi extends AuthApi {
  bool signedOut = false;

  @override
  Future<Me> fetchMe() async => Me(
        userId: 'u1',
        displayName: '홍길동',
        loginType: 'kakao',
        withdrawn: false,
        consentsCompleted: true,
        nameSet: true,
        parentRegistered: true,
        parentIds: const ['p1'],
      );

  @override
  Future<void> signOut() async => signedOut = true;
}

class FakeFamilyApi extends FamilyApi {
  FakeFamilyApi({this.role = 'admin'});

  final String role;

  @override
  Future<ParentInfo> fetchParent(String parentId) async => ParentInfo(
        id: parentId,
        nickname: '엄마',
        ageBand: '80s',
        applyStage: 'waiting',
        myRole: role,
      );
}

ParentDeletion deletion(String status, {int total = 1, int approved = 1, bool mine = true}) => ParentDeletion(
      status: status,
      requestedByName: '홍길동',
      approvalDeadline: DateTime(2026, 11, 21),
      scheduledFor: status == 'scheduled' ? DateTime(2026, 11, 21) : null,
      adminsTotal: total,
      adminsApproved: approved,
      approvedByMe: mine,
    );

class FakeSettingsApi extends SettingsApi {
  FakeSettingsApi({this.current, this.withdrawalParents = const []});

  ParentDeletion? current;
  List<WithdrawalParent> withdrawalParents;
  final calls = <String>[];
  NotificationSettings noti =
      NotificationSettings(condition: true, tasks: true, briefing: false, notiConsented: true);

  @override
  Future<NotificationSettings> fetchNotifications() async => noti;

  @override
  Future<NotificationSettings> saveNotifications(NotificationSettings settings) async {
    calls.add('noti:${settings.briefing}');
    return noti = settings;
  }

  @override
  Future<MyConsents> fetchConsents() async => MyConsents(
        current: {
          for (final t in ['service', 'privacy', 'health', 'noti'])
            t: MyConsent(type: t, agreedAt: DateTime(2026, 10, 14)),
        },
        deletionScheduledFor: null,
      );

  @override
  Future<ParentDeletion?> fetchDeletion(String parentId) async => current;

  @override
  Future<ParentDeletion> requestDeletion(String parentId) async {
    calls.add('request');
    return current = deletion('scheduled');
  }

  @override
  Future<ParentDeletion> approveDeletion(String parentId) async {
    calls.add('approve');
    return current = deletion('scheduled', total: 2, approved: 2);
  }

  @override
  Future<void> cancelDeletion(String parentId) async {
    calls.add('cancel');
    current = null;
  }

  @override
  Future<List<WithdrawalParent>> withdrawalCheck() async => withdrawalParents;

  @override
  Future<DateTime> withdraw({required bool deleteSoleParents, bool deleteMyRecords = false}) async {
    calls.add('withdraw:sole=$deleteSoleParents,records=$deleteMyRecords');
    return DateTime(2026, 11, 21);
  }

  @override
  Future<MyConsents> revokeConsent(String type, {bool deleteMyRecords = false}) async {
    calls.add('revoke:$type,records=$deleteMyRecords');
    return fetchConsents();
  }
}

void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Widget app(FakeSettingsApi api, {FakeFamilyApi? family, FakeAuthApi? auth}) {
  final router = GoRouter(
    initialLocation: '/settings',
    routes: [
      GoRoute(
        path: '/settings',
        builder: (_, _) => MyInfoScreen(
          settingsApi: api,
          familyApi: family ?? FakeFamilyApi(),
          authApi: auth ?? FakeAuthApi(),
        ),
      ),
      for (final path in ['/', '/family', '/withdrawn'])
        GoRoute(path: path, builder: (_, _) => Scaffold(body: Text('이동 $path'))),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('로그인 · 부모님 카드 · 알림 · 동의 표시', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    expect(find.text('카카오 로그인'), findsOneWidget);
    expect(find.text('엄마'), findsOneWidget);
    expect(find.text('따로 살아요'), findsOneWidget);
    expect(find.text('수정'), findsOneWidget);
    expect(find.text('건강정보 수집·이용 동의'), findsOneWidget);
    expect(find.text('2026-10-14'), findsNWidgets(4));

    // 브리핑 알림 켬 → 저장
    await tester.tap(find.byType(Switch).last);
    await tester.pumpAndSettle();
    expect(api.calls, ['noti:true']);
  });

  testWidgets('공간 삭제: 호칭 입력해야 버튼 켜짐 → 요청 → 예정일 · 취소', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(OutlinedButton, '기록 공간 삭제'));
    await tester.pumpAndSettle();
    final submit = find.widgetWithText(FilledButton, '삭제 요청');
    expect(tester.widget<FilledButton>(submit).onPressed, isNull);

    await tester.enterText(find.byType(TextField), '엄마');
    await tester.pump();
    await tester.tap(submit);
    await tester.pumpAndSettle();

    expect(api.calls, ['request']);
    expect(find.text('11월 21일에 삭제돼요'), findsOneWidget);
    // 유예 중 → 부모님 정보 수정 숨김
    expect(find.text('수정'), findsNothing);

    await tester.tap(find.text('삭제 취소'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('취소하기'));
    await tester.pumpAndSettle();
    expect(api.calls, ['request', 'cancel']);
    expect(find.widgetWithText(OutlinedButton, '기록 공간 삭제'), findsOneWidget);
  });

  testWidgets('다른 관리자 요청 대기 → 동의', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi(current: deletion('pending', total: 2, approved: 1, mine: false));
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    expect(find.textContaining('관리자 2명 중 1명 동의'), findsOneWidget);
    await tester.tap(find.text('삭제에 동의'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('동의하기'));
    await tester.pumpAndSettle();

    expect(api.calls, ['approve']);
    expect(find.text('11월 21일에 삭제돼요'), findsOneWidget);
  });

  testWidgets('관리자 아님: 삭제 요청 버튼 없음 · 유예 안내만', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi(current: deletion('scheduled'));
    await tester.pumpWidget(app(api, family: FakeFamilyApi(role: 'writer')));
    await tester.pumpAndSettle();

    expect(find.text('11월 21일에 삭제돼요'), findsOneWidget);
    expect(find.text('삭제 취소'), findsNothing);
    expect(find.text('수정'), findsNothing);
  });

  testWidgets('탈퇴: 관리자 넘기기 필요 → 가족 탭으로', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi(withdrawalParents: [
      WithdrawalParent(parentId: 'p1', nickname: '엄마', status: 'transfer_required'),
    ]);
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('탈퇴'));
    await tester.pumpAndSettle();
    expect(find.text('관리자를 먼저 넘겨 주세요'), findsOneWidget);

    await tester.tap(find.text('가족 탭으로'));
    await tester.pumpAndSettle();
    expect(find.text('이동 /family'), findsOneWidget);
    expect(api.calls, isEmpty);
  });

  testWidgets('탈퇴: 혼자 쓰는 공간 → 함께 삭제 확인 → 탈퇴', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi(withdrawalParents: [
      WithdrawalParent(parentId: 'p1', nickname: '엄마', status: 'sole_member'),
    ]);
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('탈퇴'));
    await tester.pumpAndSettle();
    expect(find.text('기록 공간도 함께 삭제돼요'), findsOneWidget);
    await tester.tap(find.text('계속'));
    await tester.pumpAndSettle();

    // 데이터 처리 안내 → 기본: 기록 유지
    expect(find.text('정말 탈퇴할까요?'), findsOneWidget);
    expect(find.textContaining('\'탈퇴한 사용자\''), findsOneWidget);
    await tester.tap(find.text('탈퇴하기'));
    await tester.pumpAndSettle();

    expect(api.calls, ['withdraw:sole=true,records=false']);
    expect(find.text('이동 /withdrawn'), findsOneWidget);
  });

  testWidgets('탈퇴: 내가 쓴 기록도 모두 지우기 선택', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi(withdrawalParents: [
      WithdrawalParent(parentId: 'p1', nickname: '엄마', status: 'ok'),
    ]);
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('탈퇴'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('내가 쓴 기록도 모두 지우기'));
    await tester.pump();
    await tester.tap(find.text('탈퇴하기'));
    await tester.pumpAndSettle();

    expect(api.calls, ['withdraw:sole=false,records=true']);
  });

  testWidgets('탈퇴: 안내에서 취소 → 탈퇴 X', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('탈퇴'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();

    expect(api.calls, isEmpty);
    expect(find.text('이동 /withdrawn'), findsNothing);
  });

  testWidgets('필수 동의 철회: 기본 기록 유지 / 지우기 선택', (tester) async {
    tallScreen(tester);
    final api = FakeSettingsApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('철회').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('동의를\n철회할까요?'), findsOneWidget);
    expect(find.textContaining('다시 동의하면 취소돼요'), findsOneWidget);
    await tester.tap(find.text('내가 쓴 기록도 모두 지우기'));
    await tester.pump();
    await tester.tap(find.text('철회하기'));
    await tester.pumpAndSettle();

    expect(api.calls, ['revoke:service,records=true']);
    // 필수 동의 없음 → 처음 화면 (동의부터)
    expect(find.text('이동 /'), findsOneWidget);
  });

  testWidgets('로그아웃 → 처음 화면', (tester) async {
    tallScreen(tester);
    final auth = FakeAuthApi();
    await tester.pumpWidget(app(FakeSettingsApi(), auth: auth));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(OutlinedButton, '로그아웃'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '로그아웃'));
    await tester.pumpAndSettle();

    expect(auth.signedOut, isTrue);
    expect(find.text('이동 /'), findsOneWidget);
  });
}
