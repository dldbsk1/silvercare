import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/home/home_api.dart';
import 'package:silvercare/features/records/records_api.dart';
import 'package:silvercare/features/records/screens/record_list_screen.dart';

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

RecordSummary record(
  String id,
  String text,
  DateTime at, {
  String area = 'physical',
  bool mine = true,
  String author = '홍길동',
  String source = 'direct',
  bool edited = false,
}) =>
    RecordSummary(
      id: id,
      authorName: author,
      isMine: mine,
      inputType: 'text',
      source: source,
      processingStatus: 'completed',
      classificationStatus: 'classified',
      currentText: text,
      areas: [area],
      recordedAt: at,
      isEdited: edited,
    );

/// 서버 흉내: 조건(영역·작성자)으로 거르기 + 요청 기록
class FakeRecordsApi extends RecordsApi {
  FakeRecordsApi(this.all);

  final List<RecordSummary> all;
  final filters = <RecordFilter>[];

  @override
  Future<RecordPage> listRecords(String parentId, RecordFilter filter, {String? cursor, int limit = 20}) async {
    filters.add(filter);
    final hits = all
        .where((r) => filter.area == null || r.areas.contains(filter.area))
        .where((r) => filter.authorId == null || (filter.authorId == 'u1') == r.isMine)
        .take(limit)
        .toList();
    return RecordPage(records: hits, nextCursor: null);
  }

  @override
  Future<List<FamilyMember>> fetchMembers(String parentId) async => [
        FamilyMember(userId: 'u1', displayName: '홍길동', isMe: true),
        FamilyMember(userId: 'u2', displayName: '형', isMe: false),
      ];
}

Widget app(FakeRecordsApi api) {
  final router = GoRouter(
    initialLocation: '/records',
    routes: [
      GoRoute(
        path: '/records',
        builder: (_, _) => RecordListScreen(recordsApi: api, authApi: FakeAuthApi()),
      ),
      GoRoute(path: '/home', builder: (_, _) => const Scaffold(body: Text('홈 화면'))),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  final day1 = DateTime(2026, 10, 13, 19, 40);
  final day0 = DateTime(2026, 10, 12, 21, 10);
  final sample = [
    record('r1', '계단 오르실 때 난간 잡으심', day1, edited: true),
    record('r2', '저녁 드신 걸 기억 못 하심', day1.subtract(const Duration(hours: 7, minutes: 30)),
        area: 'cognitive', mine: false, author: '형', source: 'call'),
    record('r3', '식사를 절반만 드심', day0),
  ];

  testWidgets('날짜별 묶음 + 카드 (시간 · 작성자 · 출처 · 수정됨)', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeRecordsApi(sample)));
    await tester.pumpAndSettle();

    expect(find.text('기록함'), findsOneWidget);
    expect(find.text('10월 13일 (화)'), findsOneWidget);
    expect(find.text('10월 12일 (월)'), findsOneWidget);
    expect(find.text('19:40 · 나 · 직접 봄 · 수정됨'), findsOneWidget);
    expect(find.text('12:10 · 형 · 통화로 들음'), findsOneWidget);
    expect(find.text('식사를 절반만 드심'), findsOneWidget);
    expect(find.text('최근 1개월'), findsOneWidget);
  });

  testWidgets('영역 필터 → 바텀시트 → 신체 고름 → 버튼 글자 바뀜 + 다시 조회', (tester) async {
    tallScreen(tester);
    final api = FakeRecordsApi(sample);
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('전체 영역'));
    await tester.pumpAndSettle();
    expect(find.text('영역'), findsOneWidget);
    expect(find.text('간호처치'), findsOneWidget);

    await tester.tap(find.text('인지').last);
    await tester.pumpAndSettle();

    expect(api.filters.last.area, 'cognitive');
    expect(find.text('저녁 드신 걸 기억 못 하심'), findsOneWidget);
    expect(find.text('계단 오르실 때 난간 잡으심'), findsNothing);
  });

  testWidgets('조건에 맞는 기록 없음', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeRecordsApi(sample)));
    await tester.pumpAndSettle();

    await tester.tap(find.text('전체 영역'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('재활'));
    await tester.pumpAndSettle();

    expect(find.text('조건에 맞는 기록이 없어요'), findsOneWidget);
  });

  testWidgets('기록 자체 없음 → 홈에서 기록하기 → 홈', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeRecordsApi([])));
    await tester.pumpAndSettle();

    expect(find.text('아직 기록이 없어요'), findsOneWidget);
    await tester.tap(find.text('홈에서 기록하기'));
    await tester.pumpAndSettle();
    expect(find.text('홈 화면'), findsOneWidget);
  });

  testWidgets('가족 필터 → 구성원 목록 (나 · 형)', (tester) async {
    tallScreen(tester);
    final api = FakeRecordsApi(sample);
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('전체 가족'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('형').last);
    await tester.pumpAndSettle();

    expect(api.filters.last.authorId, 'u2');
    expect(find.text('형'), findsWidgets);
    expect(find.text('식사를 절반만 드심'), findsNothing);
  });
}
