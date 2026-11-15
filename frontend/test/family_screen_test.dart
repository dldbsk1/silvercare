import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/family/family_api.dart';
import 'package:silvercare/features/family/screens/family_screen.dart';
import 'package:silvercare/features/home/home_api.dart';
import 'package:silvercare/features/records/records_api.dart';

class FakeAuthApi extends AuthApi {
  @override
  Future<Me> fetchMe() async => Me(
    userId: 'u1',
    displayName: '홍길동',
    withdrawn: false,
    consentsCompleted: true,
    nameSet: true,
    parentRegistered: true,
    parentIds: const ['p1'],
  );
}

class FakeFamilyApi extends FamilyApi {
  FakeFamilyApi({this.myRole = 'admin'});

  final String myRole;
  final roleChanges = <(String, String)>[];
  final revoked = <String>[];
  var created = 0;

  late List<FamilyMember> members = [
    FamilyMember(
      memberId: 'm1',
      userId: 'u1',
      displayName: '홍길동',
      role: myRole,
      isMe: true,
    ),
    FamilyMember(
      memberId: 'm2',
      userId: 'u2',
      displayName: '형',
      role: 'writer',
      isMe: false,
    ),
    FamilyMember(
      memberId: 'm3',
      userId: 'u3',
      displayName: '동생',
      role: 'viewer',
      isMe: false,
    ),
  ];

  @override
  Future<ParentInfo> fetchParent(String parentId) async => ParentInfo(
    id: parentId,
    nickname: '엄마',
    ageBand: '80s',
    applyStage: 'waiting',
    myRole: myRole,
  );

  @override
  Future<List<FamilyMember>> fetchMembers(String parentId) async => members;

  @override
  Future<int> countRecentRecords(String parentId, String authorId) async =>
      {'u1': 12, 'u2': 3, 'u3': 0}[authorId]!;

  @override
  Future<List<Invite>> fetchInvites(String parentId) async => [
    Invite(
      id: 'i1',
      role: 'writer',
      expiresAt: DateTime.now().add(const Duration(days: 4, hours: 20)),
    ),
  ];

  @override
  Future<CreatedInvite> createInvite(
    String parentId, {
    String role = 'writer',
  }) async {
    created++;
    return CreatedInvite(
      id: 'new$created',
      url: 'https://dama.test/invite#t=abc$created',
    );
  }

  @override
  Future<void> revokeInvite(String inviteId) async => revoked.add(inviteId);

  @override
  Future<void> changeRole(String memberId, String role) async {
    roleChanges.add((memberId, role));
    members = [
      for (final m in members)
        m.memberId == memberId
            ? FamilyMember(
                memberId: m.memberId,
                userId: m.userId,
                displayName: m.displayName,
                role: role,
                isMe: m.isMe,
              )
            : m,
    ];
  }

  final removed = <String>[];

  @override
  Future<void> removeMember(String memberId) async {
    removed.add(memberId);
    members = members.where((m) => m.memberId != memberId).toList();
  }

  final transfers = <String>[];

  /// 서버 흉내: 상대 → 관리자, 나 → 기록 가능 (한 번에)
  @override
  Future<List<FamilyMember>> transferAdmin(String toMemberId, {String myRole = 'writer'}) async {
    transfers.add(toMemberId);
    await changeRole(toMemberId, 'admin');
    await changeRole('m1', myRole);
    return members;
  }
}

/// 구성원 정보 화면용: 최근 기록 1건 + 전체 건수
class FakeRecordsApi extends RecordsApi {
  @override
  Future<RecordPage> listRecords(
    String parentId,
    RecordFilter filter, {
    String? cursor,
    int limit = 20,
  }) async => RecordPage(
    records: [
      RecordSummary(
        id: 'r1',
        authorName: '형',
        isMine: false,
        inputType: 'text',
        source: 'call',
        processingStatus: 'completed',
        classificationStatus: 'classified',
        currentText: '저녁 드신 걸 기억 못 하심',
        areas: const ['cognitive'],
        recordedAt: DateTime.now(),
      ),
    ],
    nextCursor: null,
    total: 41,
  );
}

void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Widget app(FakeFamilyApi api, {List<String>? shared}) => MaterialApp(
  home: FamilyScreen(
    familyApi: api,
    authApi: FakeAuthApi(),
    recordsApi: FakeRecordsApi(),
    share: (text) async => shared?.add(text),
  ),
);

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('부모님 카드 · 구성원 (역할 배지 · 30일 기록 수) · 초대 대기', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeFamilyApi()));
    await tester.pumpAndSettle();

    expect(find.text('엄마'), findsOneWidget);
    expect(find.text('80대'), findsOneWidget);
    expect(find.text('조사대기'), findsOneWidget);
    expect(find.text('구성원 3명'), findsOneWidget);
    expect(find.text('관리자'), findsOneWidget);
    expect(find.text('12건'), findsOneWidget);
    expect(find.text('3건'), findsOneWidget);
    expect(find.text('0건'), findsOneWidget);
    expect(find.text('가족 초대하기'), findsOneWidget);
    expect(find.text('초대 대기'), findsOneWidget);
    expect(find.text('5일 남음'), findsOneWidget);
  });

  testWidgets('관리자 아님 → 초대 · 초대 대기 숨김', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeFamilyApi(myRole: 'writer')));
    await tester.pumpAndSettle();

    expect(find.text('구성원 3명'), findsOneWidget);
    expect(find.text('가족 초대하기'), findsNothing);
    expect(find.text('초대 대기'), findsNothing);
  });

  /// 가족 화면에서 형 카드 누름 → 구성원 정보
  Future<void> openBrother(WidgetTester tester, FakeFamilyApi api) async {
    tallScreen(tester);
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();
    // 첫 글자 원에도 '형' → 첫 번째
    await tester.tap(find.text('형').first);
    await tester.pumpAndSettle();
    expect(find.text('구성원 정보'), findsOneWidget);
  }

  testWidgets('구성원 정보: 기록 수 · 최근 기록 · 관리 메뉴 (관리자)', (tester) async {
    await openBrother(tester, FakeFamilyApi());

    expect(find.text('3건'), findsOneWidget); // 최근 30일
    expect(find.text('41건'), findsOneWidget); // 전체
    expect(find.text('저녁 드신 걸 기억 못 하심'), findsOneWidget);
    expect(find.text('바꾸기'), findsOneWidget);
    expect(find.text('형에게 관리자 넘기기'), findsOneWidget);
    expect(find.text('가족에서 내보내기'), findsOneWidget);
  });

  testWidgets('구성원 정보: 관리자 아님 → 관리 메뉴 없음', (tester) async {
    await openBrother(tester, FakeFamilyApi(myRole: 'writer'));

    expect(find.text('41건'), findsOneWidget);
    expect(find.text('바꾸기'), findsNothing);
    expect(find.text('형에게 관리자 넘기기'), findsNothing);
    expect(find.text('가족에서 내보내기'), findsNothing);
  });

  testWidgets('권한 바꾸기 → 보기만 → 적용 → 뒤로 → 가족 화면 배지 바뀜', (tester) async {
    final api = FakeFamilyApi();
    await openBrother(tester, api);

    await tester.tap(find.text('바꾸기'));
    await tester.pumpAndSettle();
    expect(find.text('형의 권한'), findsOneWidget);
    await tester.tap(find.text('보기만'));
    await tester.tap(find.text('적용'));
    await tester.pumpAndSettle();
    expect(api.roleChanges, [('m2', 'viewer')]);

    await tester.tap(find.byTooltip('뒤로'));
    await tester.pumpAndSettle();
    expect(find.text('보기'), findsNWidgets(2));
  });

  testWidgets('관리자 넘기기 → 확인 → 형 관리자 + 나 기록 가능', (tester) async {
    final api = FakeFamilyApi();
    await openBrother(tester, api);

    await tester.tap(find.text('형에게 관리자 넘기기'));
    await tester.pumpAndSettle();
    expect(find.text('형에게 관리자를 넘길까요?'), findsOneWidget);
    await tester.tap(find.text('넘기기'));
    await tester.pumpAndSettle();

    expect(api.transfers, ['m2']);
    expect(api.roleChanges, [('m2', 'admin'), ('m1', 'writer')]);
    // 이제 관리자 아님 → 관리 메뉴 사라짐
    expect(find.text('가족에서 내보내기'), findsNothing);
  });

  testWidgets('내보내기 → 확인 → 가족 화면 구성원 2명', (tester) async {
    final api = FakeFamilyApi();
    await openBrother(tester, api);

    await tester.tap(find.text('가족에서 내보내기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('내보내기'));
    await tester.pumpAndSettle();

    expect(api.removed, ['m2']);
    expect(find.text('구성원 2명'), findsOneWidget);
  });

  testWidgets('초대 시트: 동의 체크 전 버튼 꺼짐 → 체크 → 카톡으로 초대 → 공유', (tester) async {
    tallScreen(tester);
    final api = FakeFamilyApi();
    final shared = <String>[];
    await tester.pumpWidget(app(api, shared: shared));
    await tester.pumpAndSettle();

    await tester.tap(find.text('가족 초대하기'));
    await tester.pumpAndSettle();
    final kakao = find.widgetWithText(FilledButton, '초대 링크 공유');
    expect(tester.widget<FilledButton>(kakao).onPressed, isNull);

    await tester.tap(find.byType(Checkbox));
    await tester.pump();
    await tester.tap(kakao);
    await tester.pumpAndSettle();

    expect(api.created, 1);
    expect(shared.single, contains('https://dama.test/invite#t=abc1'));
  });

  testWidgets('다시 보내기 → 새 초대 + 이전 초대 취소', (tester) async {
    tallScreen(tester);
    final api = FakeFamilyApi();
    final shared = <String>[];
    await tester.pumpWidget(app(api, shared: shared));
    await tester.pumpAndSettle();

    await tester.tap(find.text('다시 보내기'));
    await tester.pumpAndSettle();

    expect(api.created, 1);
    expect(api.revoked, ['i1']);
    expect(shared, hasLength(1));
  });
}
