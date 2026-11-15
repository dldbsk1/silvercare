import '../../core/api/api_client.dart';

/// 직접 입력 증상
const customSymptom = 'custom';

/// 시간대 → 화면 글자 (순서 = 칩 순서)
const timeBandLabels = {
  'dawn': '새벽',
  'morning': '아침',
  'afternoon': '오후',
  'evening': '저녁',
  'night': '밤',
};

/// 증상 칩 1개
class SymptomOption {
  SymptomOption({required this.type, required this.label});

  factory SymptomOption.fromJson(Map<String, dynamic> json) =>
      SymptomOption(type: json['symptom_type'] as String, label: json['label'] as String);

  /// 조사표 항목 코드
  final String type;
  final String label;
}

/// 저장할 증상
class SymptomInput {
  SymptomInput({
    required this.type,
    required this.customLabel,
    required this.timeBand,
    required this.count,
    required this.note,
  });

  final String type;

  /// 직접 입력일 때만
  final String? customLabel;
  final String timeBand;
  final int count;
  final String? note;

  Map<String, dynamic> toJson() => {
        'symptom_type': type,
        'custom_label': ?customLabel,
        'time_band': timeBand,
        'occurrence_count': count,
        if (note != null && note!.isNotEmpty) 'note': note,
      };
}

/// 최근 4주 (오래된 주 → 이번 주)
class SymptomWeekly {
  SymptomWeekly({required this.label, required this.counts});

  factory SymptomWeekly.fromJson(Map<String, dynamic> json) => SymptomWeekly(
        label: json['label'] as String,
        counts: [for (final w in json['weeks'] as List) (w as Map<String, dynamic>)['count'] as int],
      );

  final String label;
  final List<int> counts;
}

/// 증상 기록 (A-SYM-001/002)
class SymptomApi {
  SymptomApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  /// 칩 6개 (우리 가족 기록에서 많이 나온 항목 / 기록 적으면 기본)
  Future<List<SymptomOption>> fetchSuggestions(String parentId) async {
    final data = await _api.get('/parents/$parentId/symptoms/suggestions') as Map<String, dynamic>;
    return [for (final e in data['items'] as List) SymptomOption.fromJson(e as Map<String, dynamic>)];
  }

  /// 저장 → 기록 id
  Future<String> create(String parentId, SymptomInput input, {required String idempotencyKey}) async {
    final data = await _api.post(
      '/parents/$parentId/symptoms',
      body: input.toJson(),
      headers: {'Idempotency-Key': idempotencyKey},
    ) as Map<String, dynamic>;
    return data['record_id'] as String;
  }

  Future<SymptomWeekly> fetchWeekly(String parentId, String type, {String? customLabel}) async =>
      SymptomWeekly.fromJson(await _api.get(
        '/parents/$parentId/symptoms/weekly',
        query: {'symptom_type': type, 'custom_label': ?customLabel},
      ) as Map<String, dynamic>);
}
