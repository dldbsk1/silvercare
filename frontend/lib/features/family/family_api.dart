import '../../core/api/api_client.dart';

/// 역할 → 화면 글자 (배지)
const roleLabels = {'admin': '관리자', 'writer': '기록', 'viewer': '보기'};

/// 나이대 → 화면 글자
const ageBandLabels = {'60s': '60대', '70s': '70대', '80s': '80대', '90s+': '90대 이상'};

/// 신청 단계 → 화면 글자
const applyStageLabels = {
  'before': '신청 전',
  'waiting': '조사대기',
  'result': '결과 나옴',
  'renewal': '갱신 준비',
};

/// 가족 구성원 (GET /parents/{id}/family)
class FamilyMember {
  FamilyMember({
    required this.userId,
    required this.displayName,
    required this.isMe,
    this.memberId = '',
    this.role = 'writer',
    this.joinedAt,
  });

  factory FamilyMember.fromJson(Map<String, dynamic> json) => FamilyMember(
        memberId: json['member_id'] as String,
        userId: json['user_id'] as String,
        displayName: json['display_name'] as String?,
        role: json['role'] as String,
        isMe: json['is_me'] as bool,
        joinedAt: DateTime.parse(json['joined_at'] as String).toLocal(),
      );

  final String memberId;
  final String userId;
  final String? displayName;

  /// admin · writer · viewer
  final String role;
  final bool isMe;

  /// 가족이 된 날
  final DateTime? joinedAt;

  /// 이름 미설정 → "가족"
  String get name => displayName ?? '가족';

  /// 기록함 필터·목록 글자 (나 / 이름)
  String get label => isMe ? '나' : name;
}

/// 부모님 정보 (GET /parents/{id})
class ParentInfo {
  ParentInfo({
    required this.id,
    required this.nickname,
    required this.ageBand,
    required this.applyStage,
    required this.myRole,
    this.cohabiting = false,
    this.surveyDate,
  });

  factory ParentInfo.fromJson(Map<String, dynamic> json) => ParentInfo(
        id: json['id'] as String,
        nickname: json['nickname'] as String,
        ageBand: json['age_band'] as String?,
        applyStage: json['apply_stage'] as String,
        myRole: json['my_role'] as String,
        cohabiting: json['cohabiting'] as bool? ?? false,
        surveyDate: json['survey_date'] == null ? null : DateTime.parse(json['survey_date'] as String),
      );

  final String id;
  final String nickname;
  final String? ageBand;
  final String applyStage;
  final String myRole;

  /// 함께 사는지 (카드: 함께 살아요 / 따로 살아요)
  final bool cohabiting;

  /// 방문조사일 (D-day). 미정 → null
  final DateTime? surveyDate;

  bool get isAdmin => myRole == 'admin';
}

/// 부모님 정보 수정 값 (관리자). PATCH 는 보낸 필드만 변경
class ParentEdit {
  ParentEdit({
    required this.nickname,
    required this.ageBand,
    required this.applyStage,
    required this.cohabiting,
    required this.surveyDate,
  });

  final String nickname;
  final String? ageBand;
  final String applyStage;
  final bool cohabiting;
  final DateTime? surveyDate;

  Map<String, dynamic> toJson() => {
        'nickname': nickname,
        'age_band': ageBand,
        'apply_stage': applyStage,
        'cohabiting': cohabiting,
        'survey_date': surveyDate == null
            ? null
            : '${surveyDate!.year}-${surveyDate!.month.toString().padLeft(2, '0')}-${surveyDate!.day.toString().padLeft(2, '0')}',
      };
}

/// 쓸 수 있는 초대 (관리자만 조회)
class Invite {
  Invite({required this.id, required this.role, required this.expiresAt});

  factory Invite.fromJson(Map<String, dynamic> json) => Invite(
        id: json['invite_id'] as String,
        role: json['role'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String).toLocal(),
      );

  final String id;
  final String role;
  final DateTime expiresAt;

  /// 남은 날 (올림). 하루 안 남음 → 1
  int daysLeft(DateTime now) {
    final hours = expiresAt.difference(now).inHours;
    return hours <= 0 ? 0 : (hours / 24).ceil();
  }
}

/// 새 초대 (코드·링크는 이 응답에서만 받을 수 있음)
class CreatedInvite {
  CreatedInvite({required this.id, required this.code, required this.url});

  final String id;

  /// 초대 코드 (= 링크 #t= 뒤 토큰). 베타: 링크 대신 코드만 공유
  final String code;

  /// 앱 링크 도메인 정한 뒤 공유용 (지금 INVITE_BASE_URL 임시 주소)
  final String url;
}

/// 가족 탭: 부모님 · 구성원 · 초대 · 권한
class FamilyApi {
  FamilyApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  Future<ParentInfo> fetchParent(String parentId) async =>
      ParentInfo.fromJson(await _api.get('/parents/$parentId') as Map<String, dynamic>);
  /// 관리자만. 삭제 예정 공간 → 409
  Future<ParentInfo> updateParent(String parentId, ParentEdit edit) async =>
      ParentInfo.fromJson(await _api.patch('/parents/$parentId', body: edit.toJson()) as Map<String, dynamic>);


  Future<List<FamilyMember>> fetchMembers(String parentId) async {
    final data = await _api.get('/parents/$parentId/family') as List;
    return data.map((e) => FamilyMember.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// 최근 30일 (오늘 포함) 작성 기록 수. 목록 첫 페이지 meta.total 사용
  Future<int> countRecentRecords(String parentId, String authorId) async {
    final now = DateTime.now();
    final from = DateTime(now.year, now.month, now.day).subtract(const Duration(days: 29));
    final body = await _api.getPage('/parents/$parentId/records', query: {
      'author_id': authorId,
      'from': '${from.year}-${from.month.toString().padLeft(2, '0')}-${from.day.toString().padLeft(2, '0')}',
      'limit': 1,
    });
    return ((body['meta'] as Map?)?['total'] as int?) ?? 0;
  }

  /// 관리자만 (아니면 403)
  Future<List<Invite>> fetchInvites(String parentId) async {
    final data = await _api.get('/parents/$parentId/invites') as List;
    return data.map((e) => Invite.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// 초대 (7일, 1회). share_confirmed: 부모님 가족 공유 동의 확인
  Future<CreatedInvite> createInvite(String parentId, {String role = 'writer'}) async {
    final data = await _api.post(
      '/parents/$parentId/invites',
      body: {'role': role, 'share_confirmed': true},
    ) as Map<String, dynamic>;
    return CreatedInvite(
      id: data['invite_id'] as String,
      code: data['token'] as String,
      url: data['invite_url'] as String,
    );
  }

  Future<void> revokeInvite(String inviteId) => _api.delete('/invites/$inviteId');

  Future<void> changeRole(String memberId, String role) async {
    await _api.patch('/family/$memberId/role', body: {'role': role});
  }

  /// 관리자 넘기기 (서버 한 트랜잭션): 상대 → 관리자, 나 → myRole. 내 초대 코드 취소
  Future<List<FamilyMember>> transferAdmin(String toMemberId, {String myRole = 'writer'}) async {
    final data = await _api.post('/family/$toMemberId/admin-transfer', body: {'my_role': myRole}) as List;
    return data.map((e) => FamilyMember.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// 다른 사람 → 내보내기 (관리자만) / 나 → 나가기. 남긴 기록은 유지
  Future<void> removeMember(String memberId) => _api.delete('/family/$memberId');
}
