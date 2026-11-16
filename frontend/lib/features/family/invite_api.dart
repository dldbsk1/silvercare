import '../../core/api/api_client.dart';

/// 붙여넣은 글 → 초대 토큰
/// 초대 코드 8자리 (XXXX-XXXX). 대소문자·하이픈·공백·O/I/L 정리는 서버
/// 찾는 순서
/// 1. 링크 (…#t=코드, ?t=코드)
/// 2. 입력 전체가 코드 (k7qm 4xpa · K7QM4XPA 등)
/// 3. 공유 문구 안 XXXX-XXXX (앞뒤가 영문·숫자 아님)
/// 4. 예전 43자 토큰 (문구 안 20자 이상 덩어리)
/// 못 찾음 → null
String? parseInviteToken(String input) {
  final text = input.trim();
  final inLink = RegExp(r'[#?&]t=([A-Za-z0-9_-]{8,100})').firstMatch(text);
  if (inLink != null) return inLink.group(1);

  final compact = text.replaceAll(RegExp(r'[\s-]'), '');
  if (RegExp(r'^[A-Za-z0-9]{8}$').hasMatch(compact)) {
    final upper = compact.toUpperCase();
    return '${upper.substring(0, 4)}-${upper.substring(4)}';
  }

  final inMessage =
      RegExp(r'(?<![A-Za-z0-9_-])([A-Za-z0-9]{4}-[A-Za-z0-9]{4})(?![A-Za-z0-9_-])').firstMatch(text);
  if (inMessage != null) return inMessage.group(1)!.toUpperCase();

  return RegExp(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,100}(?![A-Za-z0-9_-])').firstMatch(text)?.group(0);
}

/// 가족 공유 동의 문서 (수락 시 버전 같이 보냄)
class ShareDocument {
  ShareDocument({required this.version, required this.title, required this.content});

  factory ShareDocument.fromJson(Map<String, dynamic> json) => ShareDocument(
        version: json['doc_version'] as String,
        title: json['title'] as String,
        content: json['content'] as String,
      );

  final String version;
  final String title;
  final String content;
}

/// 수락 전 확인 (POST /invites/preview)
class InvitePreview {
  InvitePreview({
    required this.inviterName,
    required this.parentNickname,
    required this.role,
    required this.expiresAt,
    required this.alreadyMember,
    required this.shareDocument,
  });

  factory InvitePreview.fromJson(Map<String, dynamic> json) => InvitePreview(
        inviterName: json['inviter_name'] as String?,
        parentNickname: json['parent_nickname'] as String,
        role: json['role'] as String,
        expiresAt: DateTime.parse(json['expires_at'] as String).toLocal(),
        alreadyMember: json['already_member'] as bool,
        shareDocument: ShareDocument.fromJson(json['share_document'] as Map<String, dynamic>),
      );

  /// 이름 미설정 → null (화면: "가족")
  final String? inviterName;
  final String parentNickname;

  /// writer · viewer
  final String role;
  final DateTime expiresAt;
  final bool alreadyMember;
  final ShareDocument shareDocument;
}

/// 초대받은 사람: 미리보기 · 수락. 토큰은 본문으로만 (URL X)
class InviteApi {
  InviteApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  /// 로그인만 필요. 없음 404 · 사용됨 409 · 취소·만료 410
  Future<InvitePreview> preview(String token) async => InvitePreview.fromJson(
        await _api.post('/invites/preview', body: {'token': token}) as Map<String, dynamic>,
      );

  /// 가족 추가 + 가족 공유 동의 기록. 반환: parent_id
  /// 동의 문서 바뀜 → 400 CONSENT_REQUIRED (미리보기 다시)
  Future<String> accept(String token, String shareDocVersion) async {
    final data = await _api.post(
      '/invites/accept',
      body: {'token': token, 'share_doc_version': shareDocVersion},
    ) as Map<String, dynamic>;
    return data['parent_id'] as String;
  }
}
