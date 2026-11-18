import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/auth/auth_api.dart';
import 'package:silvercare/core/auth/me.dart';
import 'package:silvercare/features/home/home_api.dart';
import 'package:silvercare/features/home/screens/home_screen.dart';
import 'package:silvercare/features/home/voice_recorder.dart';
import 'package:silvercare/features/notifications/notification_api.dart';

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

Map<String, dynamic> recordJson(String id, String text, {List<String> areas = const ['cognitive']}) => {
      'id': id,
      'author_name': '홍길동',
      'is_mine': true,
      'input_type': 'text',
      'source': 'direct',
      'processing_status': 'completed',
      'classification_status': 'classified',
      'current_text': text,
      'areas': areas,
      'recorded_at': DateTime.now().toUtc().toIso8601String(),
    };

class FakeHomeApi extends HomeApi {
  FakeHomeApi({this.records = const [], this.unread = 0});

  List<Map<String, dynamic>> records;
  int unread;
  final texts = <String>[];

  @override
  Future<HomeData> fetchHome(String parentId) async => HomeData.fromJson({
        'parent': {'id': parentId, 'nickname': '엄마'},
        'dday': {'survey_date': '2026-10-28', 'days_left': 3, 'status': 'upcoming'},
        'recent_records': records,
        'unread_notifications': unread,
      });

  @override
  Future<String> createText(
    String parentId, {
    required String text,
    required String source,
    required String idempotencyKey,
  }) async {
    texts.add(text);
    return 'r1';
  }

  @override
  Future<Processing> fetchProcessing(String recordId) async => Processing(
        status: 'completed',
        error: null,
        transcriptEmpty: false,
        text: '식사 때 반찬을 잘라 드렸어요',
      );

  @override
  Future<RecordResult> fetchRecord(String recordId) async => RecordResult(
        id: recordId,
        text: '식사 때 반찬을 잘라 드렸어요',
        items: [RecordItem(area: 'physical', label: '식사하기')],
      );
}

/// 임시 파일 흉내 (실제 파일 X)
class FakeAudio extends RecordedAudio {
  FakeAudio() : super('fake.m4a');

  @override
  Future<void> delete() async {}
}

/// 녹음 흉내 (실제 마이크 X)
class FakeRecorder implements VoiceRecorder {
  bool started = false;
  final _levels = StreamController<double>.broadcast();

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<void> start() async => started = true;

  @override
  Future<RecordedAudio?> stop() async => FakeAudio();

  @override
  Future<void> cancel() async {}

  @override
  Stream<double> levels() => _levels.stream;

  @override
  Future<void> dispose() => _levels.close();
}

/// 세로로 긴 화면 (목록 전체가 한 번에 그려지게)
void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

class FakeNotificationApi extends NotificationApi {
  @override
  Future<NotificationPage> fetch({String? cursor, int limit = 20}) async =>
      NotificationPage(items: const [], nextCursor: null, unreadCount: 0);
}

Widget app(FakeHomeApi api, FakeRecorder recorder, {NotificationApi? notificationApi}) {
  final router = GoRouter(
    initialLocation: '/home',
    routes: [
      GoRoute(
        path: '/home',
        builder: (_, _) => HomeScreen(
          homeApi: api,
          authApi: FakeAuthApi(),
          recorder: recorder,
          notificationApi: notificationApi,
        ),
      ),
    ],
  );
  return MaterialApp.router(routerConfig: router);
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('호칭 · D-day · 빈 최근 기록', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeHomeApi(), FakeRecorder()));
    await tester.pumpAndSettle();

    expect(find.text('엄마'), findsOneWidget);
    expect(find.text('방문조사 D-3'), findsOneWidget);
    expect(find.text('10/28(수)'), findsOneWidget);
    expect(find.text('눌러서 말하기'), findsOneWidget);
    expect(find.text('첫 기록을 남겨 보세요'), findsOneWidget);
  });

  testWidgets('알림: 안 읽음 → 종 아이콘 점 → 누르면 알림 목록 → 돌아오면 새로고침', (tester) async {
    tallScreen(tester);
    final api = FakeHomeApi(unread: 2);
    await tester.pumpWidget(app(api, FakeRecorder(), notificationApi: FakeNotificationApi()));
    await tester.pumpAndSettle();

    Badge badge() => tester.widget<Badge>(find.byKey(const Key('notification-badge')));
    expect(badge().isLabelVisible, isTrue);

    await tester.tap(find.byTooltip('알림'));
    await tester.pumpAndSettle();
    expect(find.text('아직 받은 알림이 없어요'), findsOneWidget);

    api.unread = 0;
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(badge().isLabelVisible, isFalse);
  });

  testWidgets('마이크 → 녹음 중 (정지 버튼·시간) → 2초 미만 정지 → 버리고 처음으로', (tester) async {
    tallScreen(tester);
    final recorder = FakeRecorder();
    await tester.pumpWidget(app(FakeHomeApi(), recorder));
    await tester.pumpAndSettle();

    await tester.tap(find.bySemanticsLabel('녹음 시작'));
    await tester.pump();
    expect(recorder.started, isTrue);
    expect(find.bySemanticsLabel('녹음 멈추기'), findsOneWidget);
    expect(find.text('0:00 / 3:00'), findsOneWidget);
    expect(find.text('눌러서 말하기'), findsNothing);

    await tester.tap(find.bySemanticsLabel('녹음 멈추기'));
    await tester.pumpAndSettle();
    expect(find.text('2초 이상 말해 주세요.'), findsOneWidget);
    expect(find.text('눌러서 말하기'), findsOneWidget);
  });

  testWidgets('글 저장 → 분류 결과 카드', (tester) async {
    tallScreen(tester);
    final api = FakeHomeApi();
    await tester.pumpWidget(app(api, FakeRecorder()));
    await tester.pumpAndSettle();

    final save = find.widgetWithText(FilledButton, '저장');
    expect(tester.widget<FilledButton>(save).onPressed, isNull);

    await tester.enterText(find.byType(TextField), '식사 때 반찬을 잘라 드렸어요');
    await tester.pump();
    await tester.tap(save);
    await tester.pumpAndSettle();

    expect(api.texts, ['식사 때 반찬을 잘라 드렸어요']);
    expect(find.text('신체 > 식사하기에 저장됐어요'), findsOneWidget);
    expect(find.text('분류 바꾸기'), findsOneWidget);
    expect(find.text('글 고치기'), findsOneWidget);
  });

  testWidgets('최근 기록: 시간 · 나 · 출처 / 영역 태그', (tester) async {
    tallScreen(tester);
    final api = FakeHomeApi(records: [recordJson('r9', '저녁 드신 걸 기억 못 하심')]);
    await tester.pumpWidget(app(api, FakeRecorder()));
    await tester.pumpAndSettle();

    expect(find.text('저녁 드신 걸 기억 못 하심'), findsOneWidget);
    expect(find.textContaining('· 나 · 직접 봄'), findsOneWidget);
    expect(find.text('인지'), findsOneWidget);
  });
}
