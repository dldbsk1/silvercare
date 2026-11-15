import 'dart:math';

import '../../core/api/api_client.dart';

/// 부모님 등록 값 (POST /v1/parents)
class ParentInput {
  ParentInput({
    required this.nickname,
    required this.applyStage,
    required this.cohabiting,
    this.ageBand,
  });

  /// 가족 공통 호칭 (1~20자). 이름·주민번호 X
  final String nickname;

  /// 60s · 70s · 80s · 90s+ (선택)
  final String? ageBand;

  /// before · waiting · result · renewal
  final String applyStage;
  final bool cohabiting;

  Map<String, dynamic> toJson() => {
        'nickname': nickname,
        'age_band': ageBand,
        'apply_stage': applyStage,
        'cohabiting': cohabiting,
      };
}

/// 첫 설정: 내 이름 + 부모님 등록 (동의 완료 뒤)
class SetupApi {
  SetupApi({this.client});

  /// 테스트용 교체. 기본: 처음 쓸 때 생성
  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  /// PATCH /v1/auth/me — 가족에게 보이는 이름 (1~20자)
  Future<void> updateName(String displayName) async {
    await _api.patch('/auth/me', body: {'display_name': displayName});
  }

  /// POST /v1/parents — 만든 사람 = 관리자. 같은 key로 다시 보내도 1건 (응답 유실 재시도)
  Future<void> createParent(ParentInput input, {required String idempotencyKey}) async {
    await _api.post('/parents', body: input.toJson(), headers: {'Idempotency-Key': idempotencyKey});
  }

  /// 화면 하나당 키 1개 (재시도 시 같은 키)
  static String newIdempotencyKey() {
    final random = Random.secure();
    return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }
}
