import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/api/api_exception.dart';
import 'package:silvercare/features/checklists/checklist_api.dart';
import 'package:silvercare/features/checklists/screens/checklist_answer_screen.dart';
import 'package:silvercare/features/checklists/screens/checklist_detail_screen.dart';
import 'package:silvercare/features/checklists/screens/checklist_screen.dart';
import 'package:silvercare/features/family/family_api.dart';
import 'package:silvercare/features/home/home_api.dart';

final now = DateTime(2026, 11, 17, 10);

ChecklistUser user(String id, String name, {bool me = false}) => ChecklistUser(id: id, name: name, isMe: me);

ChecklistTask task(String id, String code, String label, String scale, {String? answer, String? note}) =>
    ChecklistTask(
      taskId: id,
      itemCode: code,
      label: label,
      hint: '$label 설명',
      choices: scale == 'adl' ? ['alone', 'little', 'full', 'not_seen'] : ['yes', 'no', 'not_seen'],
      answer: answer,
      note: note,
    );

Checklist checklist({
  String id = 'c1',
  String status = 'pending',
  List<ChecklistTask>? items,
  ChecklistUser? from,
  ChecklistUser? to,
}) {
  final tasks = items ??
      [
        task('t1', 'phys_toilet_use', '화장실 사용하기', 'adl'),
        task('t2', 'beh_wandering', '길을 잃음', 'yesno'),
      ];
  return Checklist(
    id: id,
    from: from ?? user('u2', '동생'),
    to: to ?? user('u1', '홍길동', me: true),
    dueDate: DateTime(2026, 11, 18),
    status: status,
    answeredItems: tasks.where((t) => t.answer != null).length,
    totalItems: tasks.length,
    isRecipient: (to ?? user('u1', '홍길동', me: true)).isMe,
    items: tasks,
  );
}

class FakeChecklistApi extends ChecklistApi {
  FakeChecklistApi({this.suggested = const ['phys_toilet_use', 'beh_wandering']});

  final List<String> suggested;
  final calls = <String>[];
  List<Checklist> sent = [];
  List<Checklist> received = [];
  Checklist detail = checklist();
  bool failAnswer = false;

  @override
  Future<ChecklistDraft> fetchDraft(String parentId) async => ChecklistDraft(
        suggestedCodes: suggested,
        areas: [
          DraftArea(area: 'physical', label: '신체', items: [
            DraftItem(code: 'phys_dressing', label: '옷 벗고 입기', hint: '옷을 혼자 벗고 입으시는지', scale: 'adl',
                lastRecordedOn: DateTime(2026, 11, 15)),
            DraftItem(code: 'phys_toilet_use', label: '화장실 사용하기', hint: '혼자 화장실에 가시는지', scale: 'adl',
                lastRecordedOn: DateTime(2026, 9, 20), reason: 'no_records'),
          ]),
          DraftArea(area: 'behavior', label: '행동변화', items: [
            DraftItem(code: 'beh_wandering', label: '길을 잃음', hint: '익숙한 곳에서 길을 잃으신 적 있는지',
                scale: 'yesno', reason: 'no_records'),
          ]),
        ],
      );

  @override
  Future<ChecklistPage> fetchList(String parentId, {required String box, required String state}) async {
    final items = box == 'sent' ? sent : received;
    return ChecklistPage(items: items, total: items.length);
  }

  @override
  Future<Checklist> create(
    String parentId, {
    required String toUserId,
    required List<String> itemCodes,
    required DateTime dueDate,
    required String idempotencyKey,
  }) async {
    calls.add('create:$toUserId:${itemCodes.join(',')}:${dueDate.month}/${dueDate.day}');
    final created = checklist(id: 'new', from: user('u1', '홍길동', me: true), to: user(toUserId, '동생'));
    sent = [created, ...sent];
    return created;
  }

  @override
  Future<Checklist> fetch(String checklistId) async => detail;

  @override
  Future<ChecklistTask> answer(String checklistId, String taskId, {required String answer, String? note}) async {
    if (failAnswer) {
      throw ApiException(statusCode: 500, code: 'X', message: '저장하지 못했어요.');
    }
    calls.add('answer:$taskId:$answer:${note ?? ''}');
    final t = detail.items.firstWhere((t) => t.taskId == taskId);
    return t.copyWith(answer: answer, note: () => note);
  }

  @override
  Future<Checklist> submit(String checklistId) async {
    calls.add('submit:$checklistId');
    return checklist(status: 'submitted');
  }
}

class FakeFamilyApi extends FamilyApi {
  @override
  Future<List<FamilyMember>> fetchMembers(String parentId) async => [
        FamilyMember(userId: 'u1', displayName: '홍길동', isMe: true, role: 'admin'),
        FamilyMember(userId: 'u2', displayName: '동생', isMe: false, role: 'writer'),
        FamilyMember(userId: 'u3', displayName: '삼촌', isMe: false, role: 'viewer'),
      ];
}

void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Widget app(FakeChecklistApi api, {int tab = 0}) => MaterialApp(
      home: ChecklistScreen(parentId: 'p1', initialTab: tab, api: api, familyApi: FakeFamilyApi(), now: () => now),
    );

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  group('보내기 탭', () {
    testWidgets('추천 [이대로 쓰기] → 항목 체크 · 영역 N개 선택 · 마지막 기록', (tester) async {
      tallScreen(tester);
      await tester.pumpWidget(app(FakeChecklistApi()));
      await tester.pumpAndSettle();

      expect(find.text('기록이 부족한 2개 항목으로 만들었어요'), findsOneWidget);
      expect(find.text(' · 0개 선택'), findsNWidgets(2));
      // 재활 영역 없음
      expect(find.text('재활'), findsNothing);

      await tester.tap(find.text('이대로 쓰기'));
      await tester.pumpAndSettle();
      expect(find.text(' · 1개 선택'), findsNWidgets(2));
      expect(find.text('혼자 화장실에 가시는지'), findsOneWidget);
      expect(find.text('마지막 기록 9/20'), findsOneWidget);
      expect(find.text('기록 없음'), findsOneWidget);
      expect(find.text('체크리스트 보내기 · 2개 항목'), findsOneWidget);
    });

    testWidgets('추천 없음 → 안내 카드 숨김', (tester) async {
      tallScreen(tester);
      await tester.pumpWidget(app(FakeChecklistApi(suggested: const [])));
      await tester.pumpAndSettle();

      expect(find.text('이대로 쓰기'), findsNothing);
    });

    testWidgets('받을 사람 고르기 (보기 전용 X) → 보내기', (tester) async {
      tallScreen(tester);
      final api = FakeChecklistApi();
      await tester.pumpWidget(app(api));
      await tester.pumpAndSettle();

      await tester.tap(find.text('이대로 쓰기'));
      await tester.pumpAndSettle();
      // 받을 사람 없음 → 버튼 꺼짐
      final button = find.widgetWithText(FilledButton, '체크리스트 보내기 · 2개 항목');
      expect(tester.widget<FilledButton>(button).onPressed, isNull);

      await tester.tap(find.text('받을 사람'));
      await tester.pumpAndSettle();
      expect(find.text('나'), findsOneWidget);
      expect(find.text('삼촌'), findsNothing);
      await tester.tap(find.text('동생'));
      await tester.pumpAndSettle();

      await tester.tap(button);
      await tester.pumpAndSettle();

      // 조사표 순서 · 기본 확인 날짜 7일 뒤
      expect(api.calls, ['create:u2:phys_toilet_use,beh_wandering:11/24']);
      expect(find.text('체크리스트를 보냈어요.'), findsOneWidget);
      expect(find.text('동생 · 11/18'), findsOneWidget);
      expect(find.text('대기'), findsOneWidget);
    });

    testWidgets('보낸 체크리스트 → 상세', (tester) async {
      tallScreen(tester);
      final api = FakeChecklistApi()
        ..sent = [checklist(from: user('u1', '홍길동', me: true), to: user('u2', '형'))]
        ..detail = checklist(
          from: user('u1', '홍길동', me: true),
          to: user('u2', '형'),
          items: [
            task('t1', 'phys_toilet_use', '화장실 사용하기', 'adl', answer: 'little', note: '밤에는 부축이 필요해요'),
            task('t2', 'beh_wandering', '길을 잃음', 'yesno'),
          ],
        );
      await tester.pumpWidget(app(api));
      await tester.pumpAndSettle();

      await tester.tap(find.text('형 · 11/18'));
      await tester.pumpAndSettle();

      expect(find.byType(ChecklistDetailScreen), findsOneWidget);
      expect(find.text('형에게 보낸 체크리스트'), findsOneWidget);
      expect(find.text('1/2 진행'), findsOneWidget);
      expect(find.text('조금 도와드림'), findsOneWidget);
      expect(find.text('밤에는 부축이 필요해요'), findsOneWidget);
      expect(find.text('답 안 함'), findsOneWidget);
    });
  });

  group('받은 체크리스트', () {
    testWidgets('탭 숫자 · 카드 → 답하기', (tester) async {
      tallScreen(tester);
      final api = FakeChecklistApi()..received = [checklist()];
      await tester.pumpWidget(app(api, tab: 1));
      await tester.pumpAndSettle();

      expect(find.text('동생이 보냈어요'), findsOneWidget);
      expect(find.text('내일까지 · 항목 2개'), findsOneWidget);
      expect(find.text('0/2'), findsOneWidget);

      await tester.tap(find.text('시작하기'));
      await tester.pumpAndSettle();
      expect(find.byType(ChecklistAnswerScreen), findsOneWidget);
    });

    testWidgets('비었을 때', (tester) async {
      tallScreen(tester);
      await tester.pumpWidget(app(FakeChecklistApi(), tab: 1));
      await tester.pumpAndSettle();

      expect(find.text('받은 체크리스트가 없어요'), findsOneWidget);
    });
  });

  group('답하기', () {
    Widget answerApp(FakeChecklistApi api) => MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: TextButton(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => ChecklistAnswerScreen(checklist: api.detail, api: api)),
                  ),
                  child: const Text('열기'),
                ),
              ),
            ),
          ),
        );

    Future<void> open(WidgetTester tester, FakeChecklistApi api) async {
      await tester.pumpWidget(answerApp(api));
      await tester.tap(find.text('열기'));
      await tester.pumpAndSettle();
    }

    testWidgets('척도별 선택지 · 덧붙이기 · 다음 → 모두 답했어요 → 보내기', (tester) async {
      tallScreen(tester);
      final api = FakeChecklistApi();
      final before = recordsChanged.value;
      await open(tester, api);

      expect(find.text('1/2'), findsOneWidget);
      expect(find.text('화장실 사용하기'), findsOneWidget);
      for (final label in ['혼자 하심', '조금 도와드림', '다 도와드림', '못 봤어요']) {
        expect(find.text(label), findsOneWidget);
      }
      // 선택 전 [다음] 꺼짐
      expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '다음')).onPressed, isNull);

      await tester.tap(find.text('조금 도와드림'));
      await tester.pump();
      await tester.tap(find.text('한 줄 덧붙이기'));
      await tester.pump();
      await tester.enterText(find.byType(TextField), '밤에는 부축이 필요해요');
      await tester.tap(find.text('다음'));
      await tester.pumpAndSettle();

      // 예·아니오 항목
      expect(find.text('2/2'), findsOneWidget);
      expect(find.text('있었어요'), findsOneWidget);
      expect(find.text('없었어요'), findsOneWidget);
      expect(find.text('혼자 하심'), findsNothing);
      await tester.tap(find.text('없었어요'));
      await tester.pump();
      await tester.tap(find.text('다음'));
      await tester.pumpAndSettle();

      expect(find.text('모두 답했어요'), findsOneWidget);
      expect(find.text('못 봤어요로 답한 항목은 기록으로 저장하지 않고, 다음에 다시 물어봐요'), findsOneWidget);
      expect(find.text('밤에는 부축이 필요해요'), findsOneWidget);

      await tester.tap(find.text('보내기'));
      await tester.pumpAndSettle();

      expect(api.calls, ['answer:t1:little:밤에는 부축이 필요해요', 'answer:t2:no:', 'submit:c1']);
      expect(recordsChanged.value, before + 1);
      expect(find.byType(ChecklistAnswerScreen), findsNothing);
    });

    testWidgets('이어서 하기 → 첫 미답 항목부터', (tester) async {
      tallScreen(tester);
      final api = FakeChecklistApi()
        ..detail = checklist(items: [
          task('t1', 'phys_toilet_use', '화장실 사용하기', 'adl', answer: 'alone'),
          task('t2', 'beh_wandering', '길을 잃음', 'yesno'),
        ]);
      await open(tester, api);

      expect(find.text('2/2'), findsOneWidget);
      expect(find.text('길을 잃음'), findsOneWidget);
    });

    testWidgets('저장 실패 → 그 항목 그대로 + 알림', (tester) async {
      tallScreen(tester);
      final api = FakeChecklistApi()..failAnswer = true;
      await open(tester, api);

      await tester.tap(find.text('혼자 하심'));
      await tester.pump();
      await tester.tap(find.text('다음'));
      await tester.pumpAndSettle();

      expect(find.text('1/2'), findsOneWidget);
      expect(find.text('저장하지 못했어요.'), findsOneWidget);
    });
  });
}
