/// GET /v1/auth/me 응답 (온보딩 단계 판단용)
class Me {
  Me({
    required this.userId,
    this.displayName,
    this.loginType,
    required this.withdrawn,
    required this.consentsCompleted,
    required this.nameSet,
    required this.parentRegistered,
    required this.parentIds,
  });

  factory Me.fromJson(Map<String, dynamic> json) {
    final onboarding = json['onboarding'] as Map<String, dynamic>;
    final account = json['account'] as Map<String, dynamic>;
    return Me(
      userId: json['user']['id'] as String,
      displayName: json['user']['display_name'] as String?,
      loginType: json['user']['login_type'] as String?,
      withdrawn: account['status'] == 'withdrawn',
      consentsCompleted: onboarding['consents_completed'] as bool,
      nameSet: onboarding['name_set'] as bool,
      parentRegistered: onboarding['parent_registered'] as bool,
      parentIds: (json['parent_ids'] as List).cast<String>(),
    );
  }

  final String userId;

  /// 가족에게 보이는 내 이름 (미설정 → null)
  final String? displayName;

  /// 로그인 방식 (kakao · naver · google · phone · email). 모름 → null
  final String? loginType;
  final bool withdrawn;
  final bool consentsCompleted;
  final bool nameSet;
  final bool parentRegistered;
  final List<String> parentIds;

  /// 다음 화면: 탈퇴 → 동의 → 이름 + 부모님 등록 (한 화면) → 홈
  /// TODO(초대): 초대 토큰 보관 중이면 부모님 등록 대신 이름 + 초대 수락 화면
  String get nextRoute {
    if (withdrawn) return '/withdrawn';
    if (!consentsCompleted) return '/onboarding/consents';
    if (!nameSet || !parentRegistered) return '/onboarding/setup';
    return '/home';
  }
}
