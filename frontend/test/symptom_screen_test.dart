import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/features/records/screens/symptom_screen.dart';
import 'package:silvercare/features/records/symptom_api.dart';

class FakeSymptomApi extends SymptomApi {
  FakeSymptomApi({List<String>? labels})
      : labels = labels ?? ['밤에 헤매', '환청·환각', '길 잃음', '같은 말 반복', '화내기·폭언', '물건 숨기기'];

  final List<String> labels;
  final saved = <Map<String, dynamic>>[];
  final keys = <String>[];

  @override
  Future<List<SymptomOption>> fetchSuggestions(String parentId) async =>
      [for (var i = 0; i < labels.length; i++) SymptomOption(type: 'code$i', label: labels[i])];

  @override
  Future<String> create(String parentId, SymptomInput input, {required String idempotencyKey}) async {
    saved.add(input.toJson());
    keys.add(idempotencyKey);
    return 'r${saved.length}';
  }

  @override
  Future<SymptomWeekly> fetchWeekly(String parentId, String type, {String? customLabel}) async =>
      SymptomWeekly(label: customLabel ?? '밤에 헤매', counts: [1, 0, 3, saved.isEmpty ? 2 : 4]);
}

void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Widget app(FakeSymptomApi api) => MaterialApp(home: SymptomScreen(parentId: 'p1', symptomApi: api));

FilledButton saveButton(WidgetTester tester) => tester.widget<FilledButton>(find.widgetWithText(FilledButton, '저장'));

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('추천 칩 6개 + 기타 / 증상 · 시간대 골라야 저장 켜짐 → 저장', (tester) async {
    tallScreen(tester);
    final api = FakeSymptomApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    for (final label in api.labels) {
      expect(find.text(label), findsOneWidget);
    }
    expect(find.text('기타(직접 입력)'), findsOneWidget);
    expect(saveButton(tester).onPressed, isNull);

    await tester.tap(find.text('밤에 헤매'));
    await tester.pumpAndSettle();
    // 고르면 최근 4주
    expect(find.text('최근 4주'), findsOneWidget);
    expect(find.text('3번'), findsOneWidget);
    expect(saveButton(tester).onPressed, isNull);

    await tester.tap(find.text('새벽'));
    await tester.tap(find.byTooltip('한 번 늘리기'));
    await tester.pump();
    expect(find.text('2번'), findsWidgets);
    await tester.enterText(find.byType(TextField), '새벽 3시에 현관문을 열려고 하심');
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pumpAndSettle();

    expect(api.saved.single, {
      'symptom_type': 'code0',
      'time_band': 'dawn',
      'occurrence_count': 2,
      'note': '새벽 3시에 현관문을 열려고 하심',
    });
    expect(find.text('증상을 기록했어요.'), findsOneWidget);
    // 저장 뒤 막대 새로고침 + 횟수 1로
    expect(find.text('4번'), findsOneWidget);
    expect(find.text('1번'), findsWidgets);
  });

  testWidgets('기타 → 입력칸 → 이름 넣어야 저장', (tester) async {
    tallScreen(tester);
    final api = FakeSymptomApi();
    await tester.pumpWidget(app(api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('기타(직접 입력)'));
    await tester.pumpAndSettle();
    expect(find.text('기타(직접 입력)'), findsNothing);
    await tester.tap(find.text('밤'));
    await tester.pump();
    expect(saveButton(tester).onPressed, isNull);

    await tester.enterText(find.byType(TextField).first, '밥 거부');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pumpAndSettle();

    expect(api.saved.single['symptom_type'], 'custom');
    expect(api.saved.single['custom_label'], '밥 거부');
    expect(api.saved.single.containsKey('note'), isFalse);
  });

  testWidgets('횟수: 1 아래 · 20 위 못 감', (tester) async {
    tallScreen(tester);
    await tester.pumpWidget(app(FakeSymptomApi()));
    await tester.pumpAndSettle();

    final minus = tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.remove));
    expect(minus.onPressed, isNull);
    // 한 화면 갱신 안에 연타 (빠른 연속 누름) → 20 넘지 않음
    for (var i = 0; i < 25; i++) {
      await tester.tap(find.byTooltip('한 번 늘리기'), warnIfMissed: false);
    }
    await tester.pump();
    expect(find.text('20번'), findsOneWidget);
    // 20 → + 꺼짐
    final plus = tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.add));
    expect(plus.onPressed, isNull);
  });
}
