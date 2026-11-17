import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/api/api_client.dart';

/// 영역 코드 → 화면 글자 (조사표 5개 영역 + 미분류)
const areaLabels = {
  'physical': '신체',
  'cognitive': '인지',
  'behavior': '행동변화',
  'nursing': '간호처치',
  'rehab': '재활',
  'uncat': '미분류',
};

/// 기록 출처 → 화면 글자
const sourceLabels = {'direct': '직접 봄', 'call': '통화로 들음'};

/// D-day (GET /home → dday)
class Dday {
  Dday({required this.surveyDate, required this.daysLeft, required this.status});

  factory Dday.fromJson(Map<String, dynamic> json) => Dday(
        surveyDate: json['survey_date'] == null ? null : DateTime.parse(json['survey_date'] as String),
        daysLeft: json['days_left'] as int?,
        status: json['status'] as String,
      );

  final DateTime? surveyDate;

  /// 지남 → 음수, 미정 → null
  final int? daysLeft;

  /// not_set · upcoming · today · past
  final String status;
}

/// 기록 목록 한 줄 (홈 최근 기록·기록함 공통)
class RecordSummary {
  RecordSummary({
    required this.id,
    required this.authorName,
    required this.isMine,
    required this.inputType,
    required this.source,
    required this.processingStatus,
    required this.classificationStatus,
    required this.currentText,
    required this.areas,
    required this.recordedAt,
    this.isEdited = false,
  });

  factory RecordSummary.fromJson(Map<String, dynamic> json) => RecordSummary(
        isEdited: json['is_edited'] as bool? ?? false,
        id: json['id'] as String,
        authorName: json['author_name'] as String?,
        isMine: json['is_mine'] as bool,
        inputType: json['input_type'] as String,
        source: json['source'] as String,
        processingStatus: json['processing_status'] as String,
        classificationStatus: json['classification_status'] as String?,
        currentText: json['current_text'] as String?,
        areas: (json['areas'] as List).cast<String>(),
        recordedAt: DateTime.parse(json['recorded_at'] as String).toLocal(),
      );

  final String id;
  final String? authorName;
  final bool isMine;

  /// voice · text · symptom · kakao · checklist
  final String inputType;
  final String source;

  /// pending · processing · completed · failed
  final String processingStatus;

  /// classified · unclassified (완료 뒤만)
  final String? classificationStatus;
  final String? currentText;
  final List<String> areas;
  final DateTime recordedAt;

  /// 글 고침 이력 있음 → "수정됨"
  final bool isEdited;
}

/// 기록 저장 알림 (홈 저장 → 기록함 새로고침)
final recordsChanged = ValueNotifier<int>(0);

/// 홈 묶음 (GET /v1/parents/{id}/home)
class HomeData {
  HomeData({
    required this.parentId,
    required this.nickname,
    required this.dday,
    required this.recentRecords,
    this.receivedChecklists = 0,
  });

  factory HomeData.fromJson(Map<String, dynamic> json) => HomeData(
        parentId: json['parent']['id'] as String,
        nickname: json['parent']['nickname'] as String,
        dday: Dday.fromJson(json['dday'] as Map<String, dynamic>),
        recentRecords: (json['recent_records'] as List)
            .map((e) => RecordSummary.fromJson(e as Map<String, dynamic>))
            .toList(),
        receivedChecklists: json['received_checklists_open'] as int? ?? 0,
      );

  final String parentId;
  final String nickname;
  final Dday dday;
  final List<RecordSummary> recentRecords;

  /// 받은 관찰 체크리스트 중 대기 수 → 홈 카드
  final int receivedChecklists;
}

/// 처리 상태 (GET /v1/records/{id}/processing)
class Processing {
  Processing({required this.status, required this.error, required this.transcriptEmpty, required this.text});

  factory Processing.fromJson(Map<String, dynamic> json) => Processing(
        status: json['processing_status'] as String,
        error: json['processing_error'] as String?,
        transcriptEmpty: json['transcript_empty'] as bool,
        text: json['current_text'] as String?,
      );

  final String status;
  final String? error;
  final bool transcriptEmpty;
  final String? text;

  bool get done => status == 'completed' || status == 'failed';
}

/// 분류 항목 1개 (기록 상세 items)
class RecordItem {
  RecordItem({required this.area, required this.label});

  factory RecordItem.fromJson(Map<String, dynamic> json) =>
      RecordItem(area: json['area'] as String, label: json['label'] as String);

  final String area;
  final String label;

  /// 예: 신체 > 식사하기
  String get path => '${areaLabels[area] ?? area} > $label';
}

/// 기록 결과 (GET /v1/records/{id})
class RecordResult {
  RecordResult({required this.id, required this.text, required this.items});

  factory RecordResult.fromJson(Map<String, dynamic> json) => RecordResult(
        id: json['id'] as String,
        text: json['current_text'] as String?,
        items: (json['items'] as List).map((e) => RecordItem.fromJson(e as Map<String, dynamic>)).toList(),
      );

  final String id;
  final String? text;
  final List<RecordItem> items;
}

/// 음성 업로드 URL (POST .../records/audio/upload-url)
class AudioUpload {
  AudioUpload({required this.uploadId, required this.bucket, required this.path, required this.token});

  factory AudioUpload.fromJson(Map<String, dynamic> json) => AudioUpload(
        uploadId: json['upload_id'] as String,
        bucket: json['bucket'] as String,
        path: json['audio_path'] as String,
        token: json['token'] as String,
      );

  final String uploadId;
  final String bucket;
  final String path;
  final String token;
}

/// 홈: 홈 묶음 + 기록 저장 (텍스트·음성) + 처리 상태
class HomeApi {
  HomeApi({this.client});

  /// 테스트용 교체. 기본: 처음 쓸 때 생성
  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  /// 녹음 형식 (m4a = AAC). 서버 허용 형식 중 하나
  static const audioContentType = 'audio/mp4';

  Future<HomeData> fetchHome(String parentId) async =>
      HomeData.fromJson(await _api.get('/parents/$parentId/home') as Map<String, dynamic>);

  /// 텍스트 기록 → 기록 id. 분류는 서버 작업 (처리 상태로 확인)
  Future<String> createText(
    String parentId, {
    required String text,
    required String source,
    required String idempotencyKey,
  }) async {
    final data = await _api.post(
      '/parents/$parentId/records/text',
      body: {'text': text, 'source': source, 'recorded_at': _now()},
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return (data as Map<String, dynamic>)['id'] as String;
  }

  Future<AudioUpload> requestUpload(String parentId) async {
    final data = await _api.post(
      '/parents/$parentId/records/audio/upload-url',
      body: {'content_type': audioContentType},
    );
    return AudioUpload.fromJson(data as Map<String, dynamic>);
  }

  /// 서버가 발급한 서명 업로드 (앱은 Storage 직접 권한 X)
  Future<void> uploadAudio(AudioUpload upload, Uint8List bytes) async {
    await Supabase.instance.client.storage
        .from(upload.bucket)
        .uploadBinaryToSignedUrl(upload.path, upload.token, bytes, const FileOptions(contentType: audioContentType));
  }

  /// 음성 기록 → 기록 id. 받아쓰기·분류는 서버 작업
  Future<String> createVoice(
    String parentId, {
    required String uploadId,
    required int durationSeconds,
    required String source,
    required DateTime recordedAt,
    required String idempotencyKey,
  }) async {
    final data = await _api.post(
      '/parents/$parentId/records/audio',
      body: {
        'upload_id': uploadId,
        'duration_seconds': durationSeconds,
        'source': source,
        'recorded_at': recordedAt.toUtc().toIso8601String(),
      },
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return (data as Map<String, dynamic>)['id'] as String;
  }

  Future<Processing> fetchProcessing(String recordId) async =>
      Processing.fromJson(await _api.get('/records/$recordId/processing') as Map<String, dynamic>);

  Future<RecordResult> fetchRecord(String recordId) async =>
      RecordResult.fromJson(await _api.get('/records/$recordId') as Map<String, dynamic>);

  static String _now() => DateTime.now().toUtc().toIso8601String();

  /// 저장 1번당 키 1개 (재시도 → 같은 키 → 1건)
  static String newIdempotencyKey() {
    final random = Random.secure();
    return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }
}
