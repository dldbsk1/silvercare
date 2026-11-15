import '../../core/api/api_client.dart';
import '../family/family_api.dart';
import '../home/home_api.dart';

export '../family/family_api.dart' show FamilyMember;

/// 기간 필터 (기록한 날짜, 한국 시간, 오늘 포함)
enum RecordPeriod {
  all('전체 기간'),
  week('최근 1주'),
  month('최근 1개월'),
  threeMonths('최근 3개월');

  const RecordPeriod(this.label);

  final String label;

  /// 시작 날짜. 전체 → null
  DateTime? from(DateTime today) => switch (this) {
        all => null,
        week => today.subtract(const Duration(days: 6)),
        month => DateTime(today.year, today.month - 1, today.day + 1),
        threeMonths => DateTime(today.year, today.month - 3, today.day + 1),
      };
}

/// 기록함 조건 (모두 AND)
class RecordFilter {
  const RecordFilter({this.area, this.authorId, this.period = defaultPeriod});

  /// 화면 첫 기간 (Figma 기본값)
  static const defaultPeriod = RecordPeriod.month;

  /// 영역 필터의 "미분류" 값 (areaLabels 키)
  static const unclassified = 'uncat';

  final String? area;
  final String? authorId;
  final RecordPeriod period;

  bool get isDefault => area == null && authorId == null && period == defaultPeriod;

  RecordFilter copyWith({String? Function()? area, String? Function()? authorId, RecordPeriod? period}) =>
      RecordFilter(
        area: area == null ? this.area : area(),
        authorId: authorId == null ? this.authorId : authorId(),
        period: period ?? this.period,
      );

  Map<String, dynamic> toQuery(DateTime today) {
    final from = period.from(today);
    return {
      // 미분류 = 영역 X → 서버 조건 classification_status (분석 완료 + 분류 항목 없음)
      if (area == unclassified) 'classification_status': 'unclassified' else 'area': ?area,
      'author_id': ?authorId,
      if (from != null) 'from': _date(from),
    };
  }

  static String _date(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}

/// 목록 한 페이지
class RecordPage {
  RecordPage({required this.records, required this.nextCursor, this.total});

  final List<RecordSummary> records;

  /// 다음 페이지 없음 → null
  final String? nextCursor;

  /// 조건에 맞는 전체 건수 (첫 페이지만)
  final int? total;
}

/// 기록함 (GET /parents/{id}/records, 최신순 커서)
class RecordsApi {
  RecordsApi({this.client});

  final ApiClient? client;
  late final ApiClient _api = client ?? ApiClient();

  static const pageSize = 20;

  Future<RecordPage> listRecords(
    String parentId,
    RecordFilter filter, {
    String? cursor,
    int limit = pageSize,
  }) async {
    final now = DateTime.now();
    final body = await _api.getPage('/parents/$parentId/records', query: {
      ...filter.toQuery(DateTime(now.year, now.month, now.day)),
      'cursor': ?cursor,
      'limit': limit,
    });
    final meta = (body['meta'] as Map?) ?? const {};
    return RecordPage(
      records: (body['data'] as List).map((e) => RecordSummary.fromJson(e as Map<String, dynamic>)).toList(),
      nextCursor: meta['has_more'] == true ? meta['next_cursor'] as String? : null,
      total: meta['total'] as int?,
    );
  }

  Future<List<FamilyMember>> fetchMembers(String parentId) async {
    final data = await _api.get('/parents/$parentId/family') as List;
    return data.map((e) => FamilyMember.fromJson(e as Map<String, dynamic>)).toList();
  }
}
