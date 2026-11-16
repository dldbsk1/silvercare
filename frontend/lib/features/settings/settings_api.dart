import '../../core/api/api_client.dart';

/// 동의 종류 → 화면 글자 (Figma 내 정보 · 동의 관리)
const consentLabels = {
  'service': '서비스 이용 동의',
  'privacy': '개인정보 수집·이용 동의',
  'health': '건강정보 수집·이용 동의',
  'noti': '알림 수신 동의 (선택)',
};

/// 필수 동의 (철회 → 내 기록 삭제 예약)
const requiredConsents = {'service', 'privacy', 'health'};

/// 알림 설정 (GET·PUT /settings/notifications)
class NotificationSettings {
  NotificationSettings({
    required this.condition,
    required this.tasks,
    required this.briefing,
    required this.notiConsented,
  });

  factory NotificationSettings.fromJson(Map<String, dynamic> json) => NotificationSettings(
        condition: json['condition_enabled'] as bool,
        tasks: json['tasks_enabled'] as bool,
        briefing: json['briefing_enabled'] as bool,
        notiConsented: json['noti_consented'] as bool,
      );

  final bool condition;
  final bool tasks;
  final bool briefing;

  /// 알림 수신 동의 X → 설정 켜도 푸시 X
  final bool notiConsented;

  NotificationSettings copyWith({bool? condition, bool? tasks, bool? briefing}) => NotificationSettings(
        condition: condition ?? this.condition,
        tasks: tasks ?? this.tasks,
        briefing: briefing ?? this.briefing,
        notiConsented: notiConsented,
      );

  Map<String, dynamic> toJson() => {
        'condition_enabled': condition,
        'tasks_enabled': tasks,
        'briefing_enabled': briefing,
      };
}

/// 지금 유효한 동의 1건
class MyConsent {
  MyConsent({required this.type, required this.agreedAt});

  final String type;
  final DateTime agreedAt;
}

/// 동의 현황 (GET /consents/me)
class MyConsents {
  MyConsents({required this.current, required this.deletionScheduledFor});

  factory MyConsents.fromJson(Map<String, dynamic> json) => MyConsents(
        current: {
          for (final c in json['current'] as List)
            (c as Map<String, dynamic>)['type'] as String: MyConsent(
              type: c['type'] as String,
              agreedAt: DateTime.parse(c['agreed_at'] as String).toLocal(),
            ),
        },
        deletionScheduledFor: json['deletion_scheduled_for'] == null
            ? null
            : DateTime.parse(json['deletion_scheduled_for'] as String).toLocal(),
      );

  /// 종류 → 동의
  final Map<String, MyConsent> current;

  /// 필수 동의 철회 → 내 기록 삭제 예정
  final DateTime? deletionScheduledFor;
}

/// 탈퇴 전 확인: 부모님 공간별 상태
class WithdrawalParent {
  WithdrawalParent({required this.parentId, required this.nickname, required this.status});

  factory WithdrawalParent.fromJson(Map<String, dynamic> json) => WithdrawalParent(
        parentId: json['parent_id'] as String,
        nickname: json['nickname'] as String,
        status: json['status'] as String,
      );

  final String parentId;
  final String nickname;

  /// ok · transfer_required (관리자 넘기기 필요) · sole_member (혼자 → 공간도 삭제)
  final String status;
}

/// 공간 삭제 요청 (GET /parents/{id}/deletion)
class ParentDeletion {
  ParentDeletion({
    required this.status,
    required this.requestedByName,
    required this.approvalDeadline,
    required this.scheduledFor,
    required this.adminsTotal,
    required this.adminsApproved,
    required this.approvedByMe,
  });

  factory ParentDeletion.fromJson(Map<String, dynamic> json) => ParentDeletion(
        status: json['status'] as String,
        requestedByName: json['requested_by_name'] as String?,
        approvalDeadline: DateTime.parse(json['approval_deadline'] as String).toLocal(),
        scheduledFor: json['scheduled_for'] == null ? null : DateTime.parse(json['scheduled_for'] as String).toLocal(),
        adminsTotal: json['admins_total'] as int,
        adminsApproved: json['admins_approved'] as int,
        approvedByMe: json['approved_by_me'] as bool,
      );

  /// pending (관리자 동의 대기) · scheduled (유예, 읽기 전용) · executing
  final String status;
  final String? requestedByName;
  final DateTime approvalDeadline;
  final DateTime? scheduledFor;
  final int adminsTotal;
  final int adminsApproved;
  final bool approvedByMe;

  bool get isPending => status == 'pending';
}

/// 내 정보 탭: 알림 · 동의 · 탈퇴 · 공간 삭제
class SettingsApi {
  SettingsApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  Future<NotificationSettings> fetchNotifications() async =>
      NotificationSettings.fromJson(await _api.get('/settings/notifications') as Map<String, dynamic>);

  Future<NotificationSettings> saveNotifications(NotificationSettings settings) async =>
      NotificationSettings.fromJson(
        await _api.put('/settings/notifications', body: settings.toJson()) as Map<String, dynamic>,
      );

  Future<MyConsents> fetchConsents() async =>
      MyConsents.fromJson(await _api.get('/consents/me') as Map<String, dynamic>);

  /// 철회. 필수 + deleteMyRecords → 응답의 deletion_scheduled_for (7일 뒤 내 기록 삭제, 다시 동의하면 취소)
  /// deleteMyRecords X → 기록 유지
  Future<MyConsents> revokeConsent(String type, {bool deleteMyRecords = false}) async => MyConsents.fromJson(
        await _api.post('/consents/$type/revoke', body: {'delete_my_records': deleteMyRecords})
            as Map<String, dynamic>,
      );

  Future<List<WithdrawalParent>> withdrawalCheck() async {
    final data = await _api.get('/users/me/withdrawal-check') as Map<String, dynamic>;
    return (data['parents'] as List).map((e) => WithdrawalParent.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// 탈퇴 (즉시). 혼자 쓰는 공간 → deleteSoleParents 확인 필요 (7일 뒤 공간 삭제)
  /// deleteMyRecords X → 글은 가족 공간에 유지, 작성자 '탈퇴한 사용자' (음성은 삭제)
  Future<DateTime> withdraw({required bool deleteSoleParents, bool deleteMyRecords = false}) async {
    final data = await _api.post('/users/me/withdrawal', body: {
      'confirm': true,
      'delete_sole_parents': deleteSoleParents,
      'delete_my_records': deleteMyRecords,
    }) as Map<String, dynamic>;
    return DateTime.parse(data['scheduled_for'] as String).toLocal();
  }

  // ── 공간 삭제 ──

  Future<ParentDeletion?> fetchDeletion(String parentId) async {
    final data = await _api.get('/parents/$parentId/deletion');
    return data == null ? null : ParentDeletion.fromJson(data as Map<String, dynamic>);
  }

  Future<ParentDeletion> requestDeletion(String parentId) async =>
      ParentDeletion.fromJson(await _api.post('/parents/$parentId/deletion') as Map<String, dynamic>);

  Future<ParentDeletion> approveDeletion(String parentId) async =>
      ParentDeletion.fromJson(await _api.post('/parents/$parentId/deletion/approve') as Map<String, dynamic>);

  Future<void> cancelDeletion(String parentId) => _api.delete('/parents/$parentId/deletion');
}
