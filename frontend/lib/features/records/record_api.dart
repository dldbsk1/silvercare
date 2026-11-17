import '../../core/api/api_client.dart';
import '../home/home_api.dart';

/// 조사표 항목 1개 (GET /v1/survey/items). 분류 바꾸기 목록
class SurveyItem {
  SurveyItem({required this.code, required this.area, required this.label});

  factory SurveyItem.fromJson(Map<String, dynamic> json) => SurveyItem(
        code: json['code'] as String,
        area: json['area'] as String,
        label: json['label'] as String,
      );

  final String code;
  final String area;
  final String label;

  /// 예: 신체 > 식사하기
  String get path => '${areaLabels[area] ?? area} > $label';
}

/// 기록에 붙은 분류 1개
class DetailItem {
  DetailItem({required this.code, required this.area, required this.label});

  factory DetailItem.fromJson(Map<String, dynamic> json) => DetailItem(
        code: json['item_code'] as String,
        area: json['area'] as String,
        label: json['label'] as String,
      );

  final String code;
  final String area;
  final String label;

  String get path => '${areaLabels[area] ?? area} > $label';
}

/// 증상 기록 상세 (증상 기록만)
class RecordSymptom {
  RecordSymptom({required this.label, required this.timeBand, required this.count, required this.note});

  factory RecordSymptom.fromJson(Map<String, dynamic> json) => RecordSymptom(
        label: json['label'] as String,
        timeBand: json['time_band'] as String,
        count: json['occurrence_count'] as int,
        note: json['note'] as String?,
      );

  final String label;
  final String timeBand;
  final int count;
  final String? note;
}

/// 받아쓰기 실패 중 파일 문제 (다시 시도 X → 새로 녹음)
const audioProblems = {'AUDIO_MISSING', 'AUDIO_UNREADABLE', 'AUDIO_FORMAT_MISMATCH', 'AUDIO_DURATION_OUT_OF_RANGE'};

/// 기록 상세 (GET /v1/records/{id})
class RecordDetail {
  RecordDetail({
    required this.id,
    required this.isMine,
    required this.authorName,
    required this.inputType,
    required this.source,
    required this.status,
    required this.processingStatus,
    required this.stage,
    required this.processingError,
    required this.classifiedBy,
    required this.currentText,
    required this.originalText,
    required this.transcriptEmpty,
    required this.isEdited,
    required this.items,
    required this.recordedAt,
    required this.occurredAt,
    required this.editVersion,
    this.audioSeconds,
    this.audioAvailable = true,
    this.symptom,
  });

  factory RecordDetail.fromJson(Map<String, dynamic> json) => RecordDetail(
        id: json['id'] as String,
        isMine: json['is_mine'] as bool,
        authorName: json['author_name'] as String?,
        inputType: json['input_type'] as String,
        source: json['source'] as String,
        status: json['status'] as String,
        processingStatus: json['processing_status'] as String,
        stage: json['stage'] as String,
        processingError: json['processing_error'] as String?,
        classifiedBy: json['classified_by'] as String?,
        currentText: json['current_text'] as String?,
        originalText: json['original_text'] as String?,
        transcriptEmpty: json['transcript_empty'] as bool? ?? false,
        isEdited: json['is_edited'] as bool? ?? false,
        items: (json['items'] as List).map((e) => DetailItem.fromJson(e as Map<String, dynamic>)).toList(),
        recordedAt: DateTime.parse(json['recorded_at'] as String).toLocal(),
        occurredAt: json['occurred_at'] == null ? null : DateTime.parse(json['occurred_at'] as String).toLocal(),
        editVersion: json['edit_version'] as int? ?? 0,
        audioSeconds: json['audio_duration_seconds'] as int?,
        audioAvailable: json['audio_available'] as bool? ?? true,
        symptom: json['symptom'] == null ? null : RecordSymptom.fromJson(json['symptom'] as Map<String, dynamic>),
      );

  final String id;
  final bool isMine;
  final String? authorName;

  /// voice · text · symptom · kakao · checklist
  final String inputType;
  final String source;

  /// normal · excluded
  final String status;

  /// pending · processing · completed · failed
  final String processingStatus;

  /// transcription · classification · done
  final String stage;
  final String? processingError;

  /// ai · user · null (분류 전)
  final String? classifiedBy;
  final String? currentText;
  final String? originalText;
  final bool transcriptEmpty;
  final bool isEdited;
  final List<DetailItem> items;
  final DateTime recordedAt;
  final DateTime? occurredAt;

  /// 사용자 수정 순번 (실제 변경마다 +1). PATCH base_version
  final int editVersion;
  final int? audioSeconds;

  /// 재생 가능. 음성 기록인데 false → 작성자 탈퇴로 음성 삭제 (글은 유지)
  final bool audioAvailable;
  final RecordSymptom? symptom;

  bool get processing => processingStatus == 'pending' || processingStatus == 'processing';
  bool get failed => processingStatus == 'failed';
  bool get excluded => status == 'excluded';
  bool get isVoice => inputType == 'voice';

  /// 관찰 체크리스트 답 → 분류 고정 (질문한 항목)
  bool get isChecklist => inputType == 'checklist';
  bool get isSymptom => symptom != null;

  /// 받아쓰기 실패 (글 없음 → 고치기 X)
  bool get transcriptionFailed => failed && stage == 'transcription';
  bool get audioBroken => transcriptionFailed && audioProblems.contains(processingError);

  String get authorLabel => isMine ? '나' : (authorName ?? '가족');
}

/// 수정 전 상태 (이력 한 줄)
class RecordSnapshot {
  RecordSnapshot({required this.text, required this.source, required this.itemCodes});

  factory RecordSnapshot.fromJson(Map<String, dynamic> json) => RecordSnapshot(
        text: json['text'] as String?,
        source: json['source'] as String?,
        itemCodes: (json['item_codes'] as List? ?? const []).cast<String>(),
      );

  final String? text;
  final String? source;
  final List<String> itemCodes;
}

/// 수정 이력 1건
class RecordVersion {
  RecordVersion({
    required this.version,
    required this.editorName,
    required this.isMine,
    required this.editedAt,
    required this.changed,
    required this.before,
  });

  factory RecordVersion.fromJson(Map<String, dynamic> json) => RecordVersion(
        version: json['version'] as int,
        editorName: json['edited_by_name'] as String?,
        isMine: json['is_mine'] as bool,
        editedAt: DateTime.parse(json['edited_at'] as String).toLocal(),
        changed: (json['changed'] as List).cast<String>(),
        before: RecordSnapshot.fromJson(json['before'] as Map<String, dynamic>),
      );

  final int version;
  final String? editorName;
  final bool isMine;
  final DateTime editedAt;

  /// text · source · occurred_at · item_codes
  final List<String> changed;
  final RecordSnapshot before;

  String get editorLabel => isMine ? '나' : (editorName ?? '가족');
}

/// 수정 이력 (GET /v1/records/{id}/versions). history: 최신 먼저
class RecordVersions {
  RecordVersions({required this.editVersion, required this.current, required this.history});

  factory RecordVersions.fromJson(Map<String, dynamic> json) => RecordVersions(
        editVersion: json['edit_version'] as int? ?? 0,
        current: RecordSnapshot.fromJson(json['current'] as Map<String, dynamic>),
        history: (json['history'] as List).map((e) => RecordVersion.fromJson(e as Map<String, dynamic>)).toList(),
      );

  final int editVersion;
  final RecordSnapshot current;
  final List<RecordVersion> history;
}

/// 기록 상세: 조회·수정·제외·재처리·음성·조사표 항목
class RecordApi {
  RecordApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  /// 조사표 항목 (거의 안 바뀜 → 앱 실행 동안 한 번만)
  static List<SurveyItem>? _surveyCache;

  Future<RecordDetail> fetch(String recordId) async =>
      RecordDetail.fromJson(await _api.get('/records/$recordId') as Map<String, dynamic>);

  Future<RecordVersions> fetchVersions(String recordId) async =>
      RecordVersions.fromJson(await _api.get('/records/$recordId/versions') as Map<String, dynamic>);

  /// 재생 주소 (5분 유효)
  Future<String> audioUrl(String recordId) async =>
      ((await _api.get('/records/$recordId/audio')) as Map<String, dynamic>)['url'] as String;

  Future<List<SurveyItem>> surveyItems() async {
    final cached = _surveyCache;
    if (cached != null) return cached;
    final data = await _api.get('/survey/items') as List;
    return _surveyCache = data.map((e) => SurveyItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// 보낸 칸만 변경. baseVersion: 화면에서 본 editVersion (다르면 409 EDIT_CONFLICT)
  Future<RecordDetail> update(
    String recordId, {
    required int baseVersion,
    String? text,
    String? source,
    List<String>? itemCodes,
  }) async {
    final data = await _api.patch('/records/$recordId', body: {
      'base_version': baseVersion,
      'current_text': ?text,
      'source': ?source,
      'item_codes': ?itemCodes,
    });
    return RecordDetail.fromJson(data as Map<String, dynamic>);
  }

  /// 증상 고치기 (시간대·횟수·메모). note "" → 비움
  Future<RecordDetail> updateSymptom(
    String recordId, {
    required int baseVersion,
    required String timeBand,
    required int count,
    required String note,
  }) async {
    final data = await _api.patch('/records/$recordId/symptom', body: {
      'base_version': baseVersion,
      'time_band': timeBand,
      'occurrence_count': count,
      'note': note,
    });
    return RecordDetail.fromJson(data as Map<String, dynamic>);
  }

  Future<RecordDetail> exclude(String recordId) async =>
      RecordDetail.fromJson(await _api.post('/records/$recordId/exclude') as Map<String, dynamic>);

  Future<RecordDetail> include(String recordId) async =>
      RecordDetail.fromJson(await _api.post('/records/$recordId/include') as Map<String, dynamic>);

  /// 실패한 단계부터 다시 (받아쓰기 / 분류)
  Future<void> reclassify(String recordId) => _api.post('/records/$recordId/reclassify');
}
