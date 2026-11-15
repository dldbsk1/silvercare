import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/core/api/api_exception.dart';
import 'package:silvercare/features/records/record_api.dart';
import 'package:silvercare/features/records/screens/record_detail_screen.dart';
import 'package:silvercare/features/records/widgets/audio_player_bar.dart';

String utc(DateTime local) => local.toUtc().toIso8601String();

final recordedAt = DateTime(2026, 10, 13, 19, 40);

const stairs = {'item_code': 'phys_stairs', 'area': 'physical', 'label': '계단 오르기', 'confidence': 0.9, 'set_by': 'ai'};

Map<String, dynamic> rec({
  bool mine = true,
  String input = 'voice',
  String status = 'normal',
  String processing = 'completed',
  String stage = 'done',
  String? error,
  String? text = '계단 오르실 때 난간을 꼭 잡으심',
  String? original = '계단 오르실때 난간을 꼭 잡으셔',
  bool edited = false,
  bool transcriptEmpty = false,
  List<Map<String, dynamic>> items = const [stairs],
  String? classifiedBy = 'ai',
  int editVersion = 0,
  Map<String, dynamic>? symptom,
}) =>
    {
      'id': 'r1',
      'is_mine': mine,
      'author_name': mine ? '동생' : '형',
      'input_type': input,
      'source': 'direct',
      'status': status,
      'processing_status': processing,
      'stage': stage,
      'processing_error': error,
      'classified_by': classifiedBy,
      'current_text': text,
      'original_text': original,
      'transcript_empty': transcriptEmpty,
      'is_edited': edited,
      'items': items,
      'recorded_at': utc(recordedAt),
      'occurred_at': null,
      'edit_version': editVersion,
      'audio_duration_seconds': input == 'voice' ? 48 : null,
      'symptom': symptom,
    };

class FakeRecordApi extends RecordApi {
  FakeRecordApi(Map<String, dynamic> record, {List<Map<String, dynamic>>? later, this.history = const []})
      : current = Map.of(record),
        later = later ?? [];

  Map<String, dynamic> current;

  /// fetch 차례대로 (비면 current)
  final List<Map<String, dynamic>> later;
  final List<Map<String, dynamic>> history;

  final updates = <Map<String, dynamic>>[];
  final calls = <String>[];
  final updateErrors = <ApiException>[];

  RecordDetail get _detail => RecordDetail.fromJson(current);

  @override
  Future<RecordDetail> fetch(String recordId) async {
    calls.add('fetch');
    if (later.isNotEmpty) current = Map.of(later.removeAt(0));
    return _detail;
  }

  @override
  Future<RecordVersions> fetchVersions(String recordId) async => RecordVersions.fromJson({
        'edit_version': current['edit_version'],
        'original_text': current['original_text'],
        'current': {'text': current['current_text'], 'source': current['source'], 'item_codes': []},
        'history': history,
      });

  @override
  Future<String> audioUrl(String recordId) async {
    calls.add('audioUrl');
    return 'https://audio/r1';
  }

  @override
  Future<List<SurveyItem>> surveyItems() async => [
        SurveyItem(code: 'phys_eating', area: 'physical', label: '식사하기'),
        SurveyItem(code: 'phys_stairs', area: 'physical', label: '계단 오르기'),
        SurveyItem(code: 'cog_short_memory', area: 'cognitive', label: '최근 일 잊어버림'),
      ];

  @override
  Future<RecordDetail> update(
    String recordId, {
    required int baseVersion,
    String? text,
    String? source,
    List<String>? itemCodes,
  }) async {
    updates.add({'base': baseVersion, 'text': ?text, 'source': ?source, 'codes': ?itemCodes});
    if (updateErrors.isNotEmpty) throw updateErrors.removeAt(0);
    current = {
      ...current,
      'current_text': ?text,
      'source': ?source,
      if (text != null) 'is_edited': true,
      if (itemCodes != null)
        'items': [
          for (final c in itemCodes)
            {'item_code': c, 'area': c.startsWith('cog') ? 'cognitive' : 'physical', 'label': c, 'confidence': null, 'set_by': 'user'},
        ],
      'edit_version': (current['edit_version'] as int) + 1,
    };
    return _detail;
  }

  @override
  Future<RecordDetail> updateSymptom(
    String recordId, {
    required int baseVersion,
    required String timeBand,
    required int count,
    required String note,
  }) async {
    updates.add({'base': baseVersion, 'band': timeBand, 'count': count, 'note': note});
    current = {...current, 'current_text': '물건 감추기 · $timeBand · $count번', 'edit_version': baseVersion + 1};
    return _detail;
  }

  @override
  Future<RecordDetail> exclude(String recordId) async {
    calls.add('exclude');
    current = {...current, 'status': 'excluded'};
    return _detail;
  }

  @override
  Future<RecordDetail> include(String recordId) async {
    calls.add('include');
    current = {...current, 'status': 'normal'};
    return _detail;
  }

  @override
  Future<void> reclassify(String recordId) async {
    calls.add('reclassify');
    current = {...current, 'processing_status': 'pending', 'processing_error': null};
  }
}

class FakePlayback implements AudioPlayback {
  final urls = <String>[];
  final _position = StreamController<Duration>.broadcast();
  final _playing = StreamController<bool>.broadcast();
  bool played = false;

  @override
  Future<void> setUrl(String url) async => urls.add(url);

  @override
  Future<void> play() async {
    played = true;
    _playing.add(true);
  }

  @override
  Future<void> pause() async => _playing.add(false);

  @override
  Future<void> seek(Duration position) async {}

  @override
  Stream<Duration> get positionStream => _position.stream;

  @override
  Stream<bool> get playingStream => _playing.stream;

  @override
  Future<void> dispose() async {
    await _position.close();
    await _playing.close();
  }
}

void tallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Future<void> open(WidgetTester tester, FakeRecordApi api, {RecordAction? action, FakePlayback? player}) async {
  tallScreen(tester);
  await tester.pumpWidget(MaterialApp(
    home: RecordDetailScreen(
      recordId: 'r1',
      recordApi: api,
      initialAction: action,
      playerFactory: player == null ? null : () => player,
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('내 기록: 머리글 · 분류 · 글 · 바꾸기 · 출처 변경 · 글 고치기 · 제외', (tester) async {
    await open(tester, FakeRecordApi(rec()));

    expect(find.text('10/13 19:40 · 나'), findsOneWidget);
    expect(find.text('신체 > 계단 오르기'), findsOneWidget);
    expect(find.text('계단 오르실 때 난간을 꼭 잡으심'), findsOneWidget);
    expect(find.text('바꾸기'), findsOneWidget);
    expect(find.text('변경'), findsOneWidget);
    expect(find.text('글 고치기'), findsOneWidget);
    expect(find.text('기록지에서 제외'), findsOneWidget);
    expect(find.text('원문 · 10/13 19:40'), findsOneWidget);
    // 음성 기록 → 재생 막대
    expect(find.text('0:48'), findsOneWidget);
  });

  testWidgets('다른 가족 기록: 보기만 (바꾸기·고치기·제외·댓글 없음)', (tester) async {
    await open(tester, FakeRecordApi(rec(mine: false)));

    expect(find.text('10/13 19:40 · 형'), findsOneWidget);
    expect(find.text('바꾸기'), findsNothing);
    expect(find.text('변경'), findsNothing);
    expect(find.text('글 고치기'), findsNothing);
    expect(find.text('기록지에서 제외'), findsNothing);
    expect(find.text('댓글'), findsNothing);
  });

  testWidgets('수정됨 · 원문 보기 / 수정 이력 펼치기', (tester) async {
    final api = FakeRecordApi(
      {...rec(edited: true, editVersion: 2), 'source': 'call'},
      history: [
        {
          'version': 2,
          'edited_by_name': '동생',
          'is_mine': true,
          'edited_at': utc(DateTime(2026, 10, 14, 8, 2)),
          'changed': ['source'],
          'before': {'text': '계단 오르실 때 난간을 꼭 잡으심', 'source': 'direct', 'item_codes': []},
        },
        {
          'version': 1,
          'edited_by_name': '동생',
          'is_mine': true,
          'edited_at': utc(DateTime(2026, 10, 13, 21, 0)),
          'changed': ['text'],
          'before': {'text': '계단 오르실때 난간을 꼭 잡으셔', 'source': 'direct', 'item_codes': []},
        },
      ],
    );
    await open(tester, api);

    expect(find.text('계단 오르실때 난간을 꼭 잡으셔'), findsNothing);
    await tester.tap(find.text('수정됨 · 원문 보기'));
    await tester.pumpAndSettle();
    expect(find.text('계단 오르실때 난간을 꼭 잡으셔'), findsOneWidget);

    expect(find.text('수정 2번 · 10/14 08:02'), findsOneWidget);
    await tester.tap(find.text('수정 이력'));
    await tester.pumpAndSettle();
    expect(find.text('현재 · 나 · 10/14 08:02'), findsOneWidget);
    expect(find.text('출처 직접 봄 → 통화로 들음'), findsOneWidget);
    expect(find.text('수정 · 나 · 10/13 21:00'), findsOneWidget);
    expect(find.text('글 고침'), findsOneWidget);
    expect(find.text('원문 · 나 · 10/13 19:40'), findsOneWidget);
  });

  testWidgets('분류 바꾸기: 여러 개 고르기 → 순번과 함께 보냄 / 미분류 → 빈 목록', (tester) async {
    final api = FakeRecordApi(rec(editVersion: 3));
    await open(tester, api);

    await tester.tap(find.text('바꾸기'));
    await tester.pumpAndSettle();
    expect(find.text('분류 바꾸기'), findsOneWidget);
    expect(find.text('고른 항목 1개'), findsOneWidget);

    await tester.tap(find.text('식사하기'));
    await tester.tap(find.text('인지'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('최근 일 잊어버림'));
    await tester.pumpAndSettle();
    expect(find.text('고른 항목 3개'), findsOneWidget);
    await tester.tap(find.text('적용'));
    await tester.pumpAndSettle();

    expect(api.updates.single, {
      'base': 3,
      'codes': ['phys_stairs', 'phys_eating', 'cog_short_memory'],
    });
    expect(find.text('분류를 바꿨어요.'), findsOneWidget);

    await tester.tap(find.text('바꾸기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('미분류'));
    await tester.pumpAndSettle();
    expect(find.text('분류 없이 저장해요. 기록지에는 미분류로 들어가요.'), findsOneWidget);
    await tester.tap(find.text('적용'));
    await tester.pumpAndSettle();
    expect(api.updates.last, {'base': 4, 'codes': <String>[]});
    expect(find.text('미분류'), findsOneWidget);
  });

  testWidgets('글 고치기: 바꿔야 저장 켜짐 → 저장 / 고친 채 뒤로 → 버릴지 확인', (tester) async {
    final api = FakeRecordApi(rec());
    await open(tester, api);

    await tester.tap(find.text('글 고치기'));
    await tester.pumpAndSettle();
    expect(find.text('고쳐도 원문은 그대로 남아요'), findsOneWidget);
    final save = find.widgetWithText(FilledButton, '저장');
    expect(tester.widget<FilledButton>(save).onPressed, isNull);

    await tester.enterText(find.byType(TextField), '계단 오르실 때 난간을 잡으심');
    await tester.pump();
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(find.text('고친 내용을 버릴까요?'), findsOneWidget);
    await tester.tap(find.text('계속 고치기'));
    await tester.pumpAndSettle();

    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.updates.single, {'base': 0, 'text': '계단 오르실 때 난간을 잡으심'});
    expect(find.text('계단 오르실 때 난간을 잡으심'), findsOneWidget);
    expect(find.text('고쳤어요.'), findsOneWidget);
  });

  testWidgets('동시 수정: 409 → 최신 글 + 새 순번으로 다시 저장', (tester) async {
    final api = FakeRecordApi(rec(editVersion: 1));
    api.updateErrors.add(ApiException(statusCode: 409, code: 'EDIT_CONFLICT', message: '다른 곳에서 먼저 고쳤어요.'));
    await open(tester, api);

    await tester.tap(find.text('글 고치기'));
    await tester.pumpAndSettle();
    // 다른 기기에서 먼저 저장된 상태
    api.later.add(rec(editVersion: 2, text: '다른 기기 글', edited: true));
    await tester.enterText(find.byType(TextField), '내가 고친 글');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pumpAndSettle();

    expect(find.text('다른 곳에서 먼저 고쳤어요. 최신 글을 확인하고 다시 저장해 주세요.'), findsOneWidget);
    expect(find.text('최신 글: 다른 기기 글'), findsOneWidget);
    // 내 글 그대로
    expect(find.text('내가 고친 글'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pumpAndSettle();
    expect(api.updates.map((u) => u['base']), [1, 2]);
    expect(find.text('내가 고친 글'), findsOneWidget);
  });

  testWidgets('기록지에서 제외: 확인 창 → 분류 바꾸기 / 제외 → 띠 → 다시 넣기', (tester) async {
    final api = FakeRecordApi(rec());
    await open(tester, api);

    await tester.tap(find.text('기록지에서 제외'));
    await tester.pumpAndSettle();
    expect(find.text('이 기록을 기록지에서 뺄까요?'), findsOneWidget);
    await tester.tap(find.widgetWithText(OutlinedButton, '분류 바꾸기'));
    await tester.pumpAndSettle();
    expect(find.text('적용'), findsOneWidget);
    await tester.tapAt(const Offset(10, 10));
    await tester.pumpAndSettle();

    await tester.tap(find.text('기록지에서 제외'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '기록지에서 제외'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('exclude'));
    expect(find.text('기록지에서 뺀 기록이에요'), findsOneWidget);
    expect(find.text('기록지에서 제외'), findsNothing);

    await tester.tap(find.text('다시 넣기'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('include'));
    expect(find.text('기록지에서 뺀 기록이에요'), findsNothing);
  });

  testWidgets('정리 중 → 2초마다 확인 → 완료되면 분류 표시', (tester) async {
    final api = FakeRecordApi(
      rec(processing: 'processing', stage: 'classification', items: const [], classifiedBy: null),
      later: [
        rec(processing: 'processing', stage: 'classification', items: const [], classifiedBy: null),
        rec(),
      ],
    );
    await open(tester, api);
    expect(find.text('분류하는 중…'), findsOneWidget);

    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(find.text('신체 > 계단 오르기'), findsOneWidget);
    expect(find.text('분류하는 중…'), findsNothing);
  });

  testWidgets('받아쓰기 실패 → 다시 시도 / 파일 문제 → 다시 시도 없음 · 고치기 없음', (tester) async {
    final failed = rec(processing: 'failed', stage: 'transcription', error: 'STT_FAILED', text: null, original: null, items: const []);
    final api = FakeRecordApi(failed);
    await open(tester, api);

    expect(find.text('받아쓰지 못했어요.'), findsOneWidget);
    expect(find.text('글 고치기'), findsNothing);
    expect(find.text('바꾸기'), findsNothing);
    await tester.tap(find.text('다시 시도'));
    await tester.pump();
    expect(api.calls, contains('reclassify'));
    expect(find.text('받아쓰는 중…'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());

    await open(tester, FakeRecordApi({...failed, 'processing_error': 'AUDIO_UNREADABLE'}));
    expect(find.text('녹음 파일에 문제가 있어요. 다시 녹음하거나 글로 남겨 주세요.'), findsOneWidget);
    expect(find.text('다시 시도'), findsNothing);
    expect(find.text('새로 기록하기'), findsOneWidget);
  });

  testWidgets('분류 실패 → 다시 시도 + 직접 분류하기', (tester) async {
    await open(
      tester,
      FakeRecordApi(rec(processing: 'failed', stage: 'classification', error: 'CLASSIFY_FAILED', items: const [], classifiedBy: null)),
    );
    expect(find.text('분류하지 못했어요.'), findsOneWidget);
    expect(find.text('다시 시도'), findsOneWidget);
    await tester.tap(find.text('직접 분류하기'));
    await tester.pumpAndSettle();
    expect(find.text('적용'), findsOneWidget);
  });

  testWidgets('증상 기록: 증상 고치기 시트 → 시간대·횟수 보냄', (tester) async {
    final api = FakeRecordApi(rec(
      input: 'symptom',
      text: '물건 감추기 · 밤 · 2번',
      original: '물건 감추기 · 밤 · 2번',
      classifiedBy: 'user',
      symptom: {'symptom_type': 'beh_hiding', 'label': '물건 감추기', 'time_band': 'night', 'occurrence_count': 2, 'note': null},
    ));
    await open(tester, api);

    expect(find.text('글 고치기'), findsNothing);
    await tester.tap(find.text('증상 고치기'));
    await tester.pumpAndSettle();
    expect(find.text('물건 감추기 고치기'), findsOneWidget);
    await tester.tap(find.text('새벽'));
    await tester.tap(find.byTooltip('한 번 늘리기'));
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pumpAndSettle();

    expect(api.updates.single, {'base': 0, 'band': 'dawn', 'count': 3, 'note': ''});
    expect(find.text('물건 감추기 · dawn · 3번'), findsOneWidget);
  });

  testWidgets('홈 결과 카드에서 열기: 분류 바꾸기 바로 열림', (tester) async {
    await open(tester, FakeRecordApi(rec()), action: RecordAction.classify);
    expect(find.text('분류 바꾸기'), findsOneWidget);
    expect(find.text('적용'), findsOneWidget);
  });

  testWidgets('음성 재생: 처음 누를 때 재생 주소 받음', (tester) async {
    final api = FakeRecordApi(rec());
    final player = FakePlayback();
    await open(tester, api, player: player);

    await tester.tap(find.byTooltip('재생'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('audioUrl'));
    expect(player.urls, ['https://audio/r1']);
    expect(player.played, isTrue);
    expect(find.byTooltip('멈추기'), findsOneWidget);
  });
}
