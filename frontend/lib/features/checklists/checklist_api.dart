import '../../core/api/api_client.dart';

/// 답 코드 → 화면 문구 (서버 기록 글과 같은 문구)
const answerLabels = {
  'alone': '혼자 하심',
  'little': '조금 도와드림',
  'full': '다 도와드림',
  'yes': '있었어요',
  'no': '없었어요',
  'not_seen': '못 봤어요',
};

const notSeen = 'not_seen';

/// 화면 상태 배지: 완료 · 취소됨 · 나머지 대기
String statusLabel(String status) => switch (status) {
      'submitted' => '완료',
      'cancelled' => '취소됨',
      _ => '대기',
    };

DateTime? _date(Object? value) => value == null ? null : DateTime.parse(value as String);

String _ymd(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// 고르기 목록 항목
class DraftItem {
  DraftItem({
    required this.code,
    required this.label,
    required this.hint,
    required this.scale,
    this.lastRecordedOn,
    this.reason,
  });

  factory DraftItem.fromJson(Map<String, dynamic> json) => DraftItem(
        code: json['item_code'] as String,
        label: json['label'] as String,
        hint: json['hint'] as String,
        scale: json['scale'] as String,
        lastRecordedOn: _date(json['last_recorded_on']),
        reason: json['reason'] as String?,
      );

  final String code;
  final String label;

  /// "혼자 화장실에 가시는지"
  final String hint;

  /// adl · yesno
  final String scale;

  /// 마지막 기록 날짜. 없음 → "기록 없음"
  final DateTime? lastRecordedOn;

  /// no_records · few_records · not_seen_before · null
  final String? reason;
}

class DraftArea {
  DraftArea({required this.area, required this.label, required this.items});

  factory DraftArea.fromJson(Map<String, dynamic> json) => DraftArea(
        area: json['area'] as String,
        label: json['label'] as String,
        items: [for (final e in json['items'] as List) DraftItem.fromJson(e as Map<String, dynamic>)],
      );

  final String area;

  /// 신체 · 인지 · 행동변화 · 간호처치
  final String label;
  final List<DraftItem> items;
}

/// 보내기 탭: 고르기 목록 + 추천
class ChecklistDraft {
  ChecklistDraft({required this.suggestedCodes, required this.areas});

  factory ChecklistDraft.fromJson(Map<String, dynamic> json) => ChecklistDraft(
        suggestedCodes: [for (final c in json['suggested_codes'] as List) c as String],
        areas: [for (final e in json['areas'] as List) DraftArea.fromJson(e as Map<String, dynamic>)],
      );

  /// 기록이 부족한 항목 (최대 6, 없음 → 안내 카드 숨김)
  final List<String> suggestedCodes;
  final List<DraftArea> areas;
}

class ChecklistUser {
  ChecklistUser({required this.id, required this.name, required this.isMe});

  factory ChecklistUser.fromJson(Map<String, dynamic> json) => ChecklistUser(
        id: json['id'] as String,
        name: json['name'] as String?,
        isMe: json['is_me'] as bool,
      );

  final String id;
  final String? name;
  final bool isMe;

  /// 나 / 이름 / 이름 없음 → 가족
  String get label => isMe ? '나' : (name ?? '가족');
}

/// 체크리스트 항목 하나
class ChecklistTask {
  ChecklistTask({
    required this.taskId,
    required this.itemCode,
    required this.label,
    required this.hint,
    required this.choices,
    this.answer,
    this.note,
    this.recordId,
  });

  factory ChecklistTask.fromJson(Map<String, dynamic> json) => ChecklistTask(
        taskId: json['task_id'] as String,
        itemCode: json['item_code'] as String,
        label: json['label'] as String,
        hint: json['hint'] as String,
        choices: [for (final c in json['choices'] as List) c as String],
        answer: json['answer'] as String?,
        note: json['note'] as String?,
        recordId: json['record_id'] as String?,
      );

  final String taskId;
  final String itemCode;
  final String label;
  final String hint;

  /// 척도별 선택지 (화면 순서)
  final List<String> choices;
  final String? answer;
  final String? note;

  /// 보낸 뒤 생긴 기록 (못 봤어요 → null)
  final String? recordId;

  ChecklistTask copyWith({String? answer, String? Function()? note}) => ChecklistTask(
        taskId: taskId,
        itemCode: itemCode,
        label: label,
        hint: hint,
        choices: choices,
        answer: answer ?? this.answer,
        note: note == null ? this.note : note(),
        recordId: recordId,
      );
}

/// 체크리스트 (목록: items 비어 있음)
class Checklist {
  Checklist({
    required this.id,
    required this.from,
    required this.to,
    required this.dueDate,
    required this.status,
    required this.answeredItems,
    required this.totalItems,
    this.isRecipient = false,
    this.items = const [],
  });

  factory Checklist.fromJson(Map<String, dynamic> json) => Checklist(
        id: json['id'] as String,
        from: ChecklistUser.fromJson(json['from_user'] as Map<String, dynamic>),
        to: ChecklistUser.fromJson(json['to_user'] as Map<String, dynamic>),
        dueDate: DateTime.parse(json['due_date'] as String),
        status: json['status'] as String,
        answeredItems: json['answered_items'] as int,
        totalItems: json['total_items'] as int,
        isRecipient: json['is_recipient'] as bool? ?? false,
        items: [
          for (final e in (json['items'] as List?) ?? const []) ChecklistTask.fromJson(e as Map<String, dynamic>)
        ],
      );

  final String id;
  final ChecklistUser from;
  final ChecklistUser to;
  final DateTime dueDate;

  /// pending · in_progress · overdue · submitted · cancelled
  final String status;
  final int answeredItems;
  final int totalItems;
  final bool isRecipient;
  final List<ChecklistTask> items;

  bool get isOpen => status != 'submitted' && status != 'cancelled';
}

/// 받은·보낸 목록
class ChecklistPage {
  ChecklistPage({required this.items, required this.total});

  final List<Checklist> items;
  final int total;
}

/// 관찰 체크리스트 (A-TASK, SCR_A_310)
class ChecklistApi {
  ChecklistApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  Future<ChecklistDraft> fetchDraft(String parentId) async =>
      ChecklistDraft.fromJson(await _api.get('/parents/$parentId/checklists/draft') as Map<String, dynamic>);

  Future<Checklist> create(
    String parentId, {
    required String toUserId,
    required List<String> itemCodes,
    required DateTime dueDate,
    required String idempotencyKey,
  }) async =>
      Checklist.fromJson(await _api.post(
        '/parents/$parentId/checklists',
        body: {'to_user_id': toUserId, 'item_codes': itemCodes, 'due_date': _ymd(dueDate)},
        headers: {'Idempotency-Key': idempotencyKey},
      ) as Map<String, dynamic>);

  /// box: received · sent / state: open · done · all
  Future<ChecklistPage> fetchList(String parentId, {required String box, required String state}) async {
    final page = await _api.getPage('/parents/$parentId/checklists', query: {'box': box, 'state': state});
    return ChecklistPage(
      items: [for (final e in page['data'] as List) Checklist.fromJson(e as Map<String, dynamic>)],
      total: (page['meta'] as Map)['total'] as int,
    );
  }

  Future<Checklist> fetch(String checklistId) async =>
      Checklist.fromJson(await _api.get('/checklists/$checklistId') as Map<String, dynamic>);

  /// 항목 하나 답 → 저장된 항목
  Future<ChecklistTask> answer(String checklistId, String taskId, {required String answer, String? note}) async {
    final data = await _api.put(
      '/checklists/$checklistId/items/$taskId/answer',
      body: {'answer': answer, 'note': note},
    ) as Map<String, dynamic>;
    return ChecklistTask.fromJson(data['item'] as Map<String, dynamic>);
  }

  /// 모두 답했어요 → 보내기 (못 봤어요 제외 답마다 기록)
  Future<Checklist> submit(String checklistId) async =>
      Checklist.fromJson(await _api.post('/checklists/$checklistId/submit') as Map<String, dynamic>);
}
