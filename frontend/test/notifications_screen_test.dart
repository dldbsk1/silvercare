import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/features/notifications/notification_api.dart';
import 'package:silvercare/features/notifications/screens/notifications_screen.dart';

AppNotification note(String id, String title, {bool read = false, String type = 'record_comment', String? body}) =>
    AppNotification(
      id: id,
      type: type,
      parentId: 'p1',
      title: title,
      body: body,
      payload: const {'record_id': 'r1'},
      createdAt: DateTime.now().subtract(const Duration(minutes: 5)),
      readAt: read ? DateTime.now() : null,
    );

class FakeNotificationApi extends NotificationApi {
  FakeNotificationApi(this.pages);

  /// 커서 → 페이지 (null = 첫 페이지)
  final Map<String?, NotificationPage> pages;
  final calls = <String>[];

  @override
  Future<NotificationPage> fetch({String? cursor, int limit = 20}) async {
    calls.add('fetch:${cursor ?? 'first'}');
    return pages[cursor]!;
  }

  @override
  Future<void> markRead(String notificationId) async => calls.add('read:$notificationId');

  @override
  Future<void> markAllRead() async => calls.add('readAll');
}

Future<void> open(WidgetTester tester, FakeNotificationApi api, {List<AppNotification>? opened}) async {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    home: NotificationsScreen(
      api: api,
      onOpen: (context, n) async => opened?.add(n),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('목록: 제목 · 본문 · 시간 · 안 읽음 점', (tester) async {
    await open(tester, FakeNotificationApi({
      null: NotificationPage(
        items: [note('n1', '형님이 내 기록에 댓글을 남겼어요', body: '저도 봤어요'), note('n2', '체크리스트가 취소됐어요', read: true)],
        nextCursor: null,
        unreadCount: 1,
      ),
    }));

    expect(find.text('형님이 내 기록에 댓글을 남겼어요'), findsOneWidget);
    expect(find.text('저도 봤어요'), findsOneWidget);
    expect(find.text('5분 전'), findsNWidgets(2));
    expect(find.byKey(const Key('unread-dot')), findsOneWidget);
    expect(find.text('모두 읽음'), findsOneWidget);
  });

  testWidgets('누르면 읽음 + 해당 화면', (tester) async {
    final opened = <AppNotification>[];
    final api = FakeNotificationApi({
      null: NotificationPage(items: [note('n1', '댓글')], nextCursor: null, unreadCount: 1),
    });
    await open(tester, api, opened: opened);

    await tester.tap(find.text('댓글'));
    await tester.pumpAndSettle();

    expect(api.calls, contains('read:n1'));
    expect(opened.single.id, 'n1');
    expect(find.byKey(const Key('unread-dot')), findsNothing);
    expect(find.text('모두 읽음'), findsNothing);
  });

  testWidgets('모두 읽음 → 점 사라짐', (tester) async {
    final api = FakeNotificationApi({
      null: NotificationPage(items: [note('n1', '하나'), note('n2', '둘')], nextCursor: null, unreadCount: 2),
    });
    await open(tester, api);

    await tester.tap(find.text('모두 읽음'));
    await tester.pumpAndSettle();

    expect(api.calls, contains('readAll'));
    expect(find.byKey(const Key('unread-dot')), findsNothing);
  });

  testWidgets('끝까지 → 다음 페이지', (tester) async {
    final api = FakeNotificationApi({
      null: NotificationPage(items: [note('n1', '첫 번째', read: true)], nextCursor: 'c2', unreadCount: 0),
      'c2': NotificationPage(items: [note('n2', '두 번째', read: true)], nextCursor: null, unreadCount: 0),
    });
    await open(tester, api);

    expect(api.calls, ['fetch:first', 'fetch:c2']);
    expect(find.text('두 번째'), findsOneWidget);
  });

  testWidgets('없음 → 안내', (tester) async {
    await open(tester, FakeNotificationApi({
      null: NotificationPage(items: const [], nextCursor: null, unreadCount: 0),
    }));
    expect(find.text('아직 받은 알림이 없어요'), findsOneWidget);
  });

  test('시간 표시', () {
    final now = DateTime(2026, 11, 18, 15);
    expect(timeAgo(now.subtract(const Duration(seconds: 20)), now: now), '방금');
    expect(timeAgo(now.subtract(const Duration(minutes: 12)), now: now), '12분 전');
    expect(timeAgo(now.subtract(const Duration(hours: 3)), now: now), '3시간 전');
    expect(timeAgo(DateTime(2026, 11, 17, 22), now: now), '어제');
    expect(timeAgo(DateTime(2026, 11, 5, 9), now: now), '11/5');
  });
}
