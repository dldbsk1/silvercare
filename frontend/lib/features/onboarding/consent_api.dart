import '../../core/api/api_client.dart';

/// 동의 문서 1개 (GET /v1/consents/required)
class ConsentDocument {
  ConsentDocument({
    required this.type,
    required this.required,
    required this.docVersion,
    required this.title,
    required this.content,
  });

  factory ConsentDocument.fromJson(Map<String, dynamic> json) => ConsentDocument(
        type: json['type'] as String,
        required: json['required'] as bool,
        docVersion: json['doc_version'] as String,
        title: json['title'] as String,
        content: json['content'] as String,
      );

  /// service · privacy · health · noti
  final String type;
  final bool required;
  final String docVersion;
  final String title;
  final String content;
}

/// 가입 동의 (A-ON-002). 로그인만 필요 (동의 전 호출)
class ConsentApi {
  ConsentApi({this.client});

  /// 테스트용 교체. 기본: 처음 쓸 때 생성
  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  Future<List<ConsentDocument>> fetchRequired() async {
    final data = await _api.get('/consents/required') as List;
    return data.map((e) => ConsentDocument.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// 문서 전부 한 번에 (필수 = true, 선택 = 체크 여부). 버전은 받은 문서 그대로
  Future<void> save(List<ConsentDocument> documents, Set<String> agreed) async {
    await _api.post('/consents', body: {
      'items': [
        for (final doc in documents)
          {'type': doc.type, 'doc_version': doc.docVersion, 'agreed': agreed.contains(doc.type)},
      ],
    });
  }
}
