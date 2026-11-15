import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../home/home_api.dart';
import '../records_api.dart';
import '../widgets/record_card.dart';
import 'symptom_screen.dart';

/// SCR_A_200 기록함
/// - 최신순, 날짜별 묶음, 20개씩 이어 불러오기 (커서)
/// - 필터: 영역 · 가족(작성자) · 기간 → 바텀시트 (모두 AND)
/// - 빈 화면 2종: 기록 자체 없음 / 조건에 맞는 기록 없음
class RecordListScreen extends StatefulWidget {
  const RecordListScreen({super.key, this.recordsApi, this.authApi});

  /// 테스트용 교체
  final RecordsApi? recordsApi;
  final AuthApi? authApi;

  @override
  State<RecordListScreen> createState() => _RecordListScreenState();
}

class _RecordListScreenState extends State<RecordListScreen> {
  late final RecordsApi _api = widget.recordsApi ?? RecordsApi();
  late final AuthApi _auth = widget.authApi ?? AuthApi();
  final _scroll = ScrollController();

  String? _parentId;
  RecordFilter _filter = const RecordFilter();
  List<RecordSummary> _records = [];
  String? _cursor;
  List<FamilyMember>? _members;

  bool _loading = true;
  bool _loadingMore = false;
  String? _error;

  /// 조건 없이도 기록 0건 → "아직 기록이 없어요"
  bool _noRecordsAtAll = false;

  /// 늦게 온 이전 조건 응답 무시용
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    recordsChanged.addListener(_reload);
    _reload();
  }

  @override
  void dispose() {
    recordsChanged.removeListener(_reload);
    _scroll.dispose();
    super.dispose();
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  // ── 불러오기 ──

  /// 첫 페이지부터 (조건 변경·새로고침·홈 저장)
  Future<void> _reload() async {
    final generation = ++_generation;
    setState(() {
      _error = null;
      if (_records.isEmpty) _loading = true;
    });
    try {
      _parentId ??= await _loadParentId();
      final page = await _api.listRecords(_parentId!, _filter);
      var noRecordsAtAll = false;
      if (page.records.isEmpty && _filter.area == null && _filter.authorId == null) {
        noRecordsAtAll = _filter.period == RecordPeriod.all ||
            (await _api.listRecords(_parentId!, const RecordFilter(period: RecordPeriod.all), limit: 1))
                .records
                .isEmpty;
      }
      if (!mounted || generation != _generation) return;
      setState(() {
        _records = page.records;
        _cursor = page.nextCursor;
        _noRecordsAtAll = noRecordsAtAll;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _loading = false;
        if (_records.isEmpty) _error = e.message;
      });
      if (_records.isNotEmpty) _toast(e.message);
    }
  }

  Future<String> _loadParentId() async {
    final me = await _auth.fetchMe();
    if (me.parentIds.isEmpty) {
      throw ApiException(statusCode: 0, code: 'NO_PARENT', message: '등록된 부모님이 없어요.');
    }
    return me.parentIds.first;
  }

  /// 다음 페이지 (끝 근처까지 내리면)
  Future<void> _loadMore() async {
    final cursor = _cursor;
    if (cursor == null || _loadingMore || _loading) return;
    final generation = _generation;
    setState(() => _loadingMore = true);
    try {
      final page = await _api.listRecords(_parentId!, _filter, cursor: cursor);
      if (!mounted || generation != _generation) return;
      setState(() {
        _records = [..._records, ...page.records];
        _cursor = page.nextCursor;
      });
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _onScroll() {
    if (_scroll.position.extentAfter < 300) _loadMore();
  }

  void _applyFilter(RecordFilter filter) {
    setState(() {
      _filter = filter;
      _records = [];
      _cursor = null;
      _loading = true;
    });
    _reload();
  }

  // ── 증상 기록 ──

  /// 저장 → recordsChanged → 목록 자동 새로고침
  void _openSymptom() {
    final parentId = _parentId;
    if (parentId == null) return;
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => SymptomScreen(parentId: parentId)));
  }

  // ── 필터 바텀시트 ──

  Future<void> _pickArea() async {
    final picked = await _showOptions<String?>(
      title: '영역',
      selected: _filter.area,
      options: [
        (null, '전체 영역'),
        for (final e in areaLabels.entries) (e.key, e.value),
      ],
    );
    if (picked != null && picked.$1 != _filter.area) {
      _applyFilter(_filter.copyWith(area: () => picked.$1));
    }
  }

  Future<void> _pickAuthor() async {
    final parentId = _parentId;
    if (parentId == null) return;
    if (_members == null) {
      try {
        _members = await _api.fetchMembers(parentId);
      } on ApiException catch (e) {
        if (mounted) _toast(e.message);
        return;
      }
    }
    if (!mounted) return;
    final picked = await _showOptions<String?>(
      title: '가족',
      selected: _filter.authorId,
      options: [
        (null, '전체 가족'),
        for (final m in _members!) (m.userId, m.label),
      ],
    );
    if (picked != null && picked.$1 != _filter.authorId) {
      _applyFilter(_filter.copyWith(authorId: () => picked.$1));
    }
  }

  Future<void> _pickPeriod() async {
    final picked = await _showOptions<RecordPeriod>(
      title: '기간',
      selected: _filter.period,
      options: [for (final p in RecordPeriod.values) (p, p.label)],
    );
    if (picked != null && picked.$1 != _filter.period) {
      _applyFilter(_filter.copyWith(period: picked.$1));
    }
  }

  /// 선택지 바텀시트. 닫기 → null / 고름 → (값,)
  Future<(T,)?> _showOptions<T>({
    required String title,
    required T selected,
    required List<(T, String)> options,
  }) {
    return showModalBottomSheet<(T,)>(
      context: context,
      // 기본 높이 제한(화면 9/16) X → 내용만큼. 넘치면 시트 안에서 스크롤
      isScrollControlled: true,
      backgroundColor: Colors.white,
      barrierColor: AppColors.text.withValues(alpha: 0.45),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (context) => _OptionSheet<T>(title: title, selected: selected, options: options),
    );
  }

  // ── 화면 ──

  String get _areaLabel => _filter.area == null ? '전체 영역' : areaLabels[_filter.area] ?? _filter.area!;

  String get _authorLabel {
    final id = _filter.authorId;
    if (id == null) return '전체 가족';
    return _members?.where((m) => m.userId == id).firstOrNull?.label ?? '가족';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _reload,
          child: ListView(
            controller: _scroll,
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            children: [
              const Text(
                '기록함',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
              ),
              const SizedBox(height: 18),
              OutlinedButton(
                onPressed: _openSymptom,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.primary,
                  side: const BorderSide(color: AppColors.primaryGlow, width: 1.5),
                  minimumSize: const Size.fromHeight(52),
                  shape: const StadiumBorder(),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                child: const Text('증상 기록'),
              ),
              const SizedBox(height: 16),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    _FilterPill(label: _areaLabel, active: _filter.area != null, onTap: _pickArea),
                    const SizedBox(width: 5),
                    _FilterPill(label: _authorLabel, active: _filter.authorId != null, onTap: _pickAuthor),
                    const SizedBox(width: 5),
                    _FilterPill(
                      label: _filter.period.label,
                      active: _filter.period != RecordFilter.defaultPeriod,
                      onTap: _pickPeriod,
                    ),
                  ],
                ),
              ),
              ..._content(),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _content() {
    if (_loading) {
      return const [
        Padding(padding: EdgeInsets.only(top: 120), child: Center(child: CircularProgressIndicator())),
      ];
    }
    if (_error != null) {
      return [
        const SizedBox(height: 120),
        _Message(_error!),
        const SizedBox(height: 16),
        Center(child: TextButton(onPressed: _reload, child: const Text('다시 시도'))),
      ];
    }
    if (_records.isEmpty && _noRecordsAtAll) {
      return [
        const SizedBox(height: 92),
        const _Message('아직 기록이 없어요'),
        const SizedBox(height: 12),
        const _Message('홈에서 첫 기록을 남겨 보세요'),
        const SizedBox(height: 20),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: FilledButton(
            onPressed: () => context.go('/home'),
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primaryGlow,
              foregroundColor: Colors.white,
              minimumSize: const Size.fromHeight(52),
              shape: const StadiumBorder(),
              textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            child: const Text('홈에서 기록하기'),
          ),
        ),
      ];
    }
    if (_records.isEmpty) {
      return const [SizedBox(height: 120), _Message('조건에 맞는 기록이 없어요')];
    }

    final widgets = <Widget>[];
    DateTime? day;
    for (final record in _records) {
      final t = record.recordedAt;
      final recordDay = DateTime(t.year, t.month, t.day);
      if (recordDay != day) {
        widgets
          ..add(SizedBox(height: day == null ? 10 : 20))
          ..add(_DayHeader(recordDay))
          ..add(const SizedBox(height: 8));
        day = recordDay;
      } else {
        widgets.add(const SizedBox(height: 8));
      }
      widgets.add(RecordCard(
        record: record,
        showDay: false,
        onTap: () => _toast('기록 상세는 준비 중이에요.'),
      ));
    }
    if (_loadingMore) {
      widgets.add(const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Center(child: CircularProgressIndicator()),
      ));
    }
    return widgets;
  }
}

/// 필터 버튼 (Figma: 흰 바탕 + 회색 테두리 / 고름 → mint 바탕 + 진녹색 글자)
class _FilterPill extends StatelessWidget {
  const _FilterPill({required this.label, required this.active, required this.onTap});

  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = active ? AppColors.primary : AppColors.text;
    return Material(
      color: active ? AppColors.mint : Colors.white,
      shape: const StadiumBorder(side: BorderSide(color: AppColors.track)),
      child: InkWell(
        onTap: onTap,
        customBorder: const StadiumBorder(),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 12, 10),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(label, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: color)),
              const SizedBox(width: 4),
              Icon(Icons.keyboard_arrow_down, size: 24, color: color),
            ],
          ),
        ),
      ),
    );
  }
}

/// 날짜 머리글 (예: 10월 13일 (화))
class _DayHeader extends StatelessWidget {
  const _DayHeader(this.day);

  final DateTime day;

  static const _weekdays = ['월', '화', '수', '목', '금', '토', '일'];

  @override
  Widget build(BuildContext context) {
    return Text(
      '${day.month}월 ${day.day}일 (${_weekdays[day.weekday - 1]})',
      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      textAlign: TextAlign.center,
      style: const TextStyle(fontSize: 16, color: AppColors.subtext),
    );
  }
}

/// 필터 바텀시트 (Figma: 손잡이 / 제목 / 선택지 칩. 고름 → mint + 진녹색 테두리)
class _OptionSheet<T> extends StatelessWidget {
  const _OptionSheet({required this.title, required this.selected, required this.options});

  final String title;
  final T selected;
  final List<(T, String)> options;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 44,
                height: 5,
                decoration: BoxDecoration(color: AppColors.track, borderRadius: BorderRadius.circular(3)),
              ),
            ),
            const SizedBox(height: 16),
            Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text)),
            const SizedBox(height: 40),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final (value, label) in options)
                  _OptionChip(
                    label: label,
                    selected: value == selected,
                    onTap: () => Navigator.of(context).pop((value,)),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _OptionChip extends StatelessWidget {
  const _OptionChip({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      selected: selected,
      button: true,
      child: Material(
        color: selected ? AppColors.mint : Colors.white,
        shape: StadiumBorder(side: BorderSide(color: selected ? AppColors.primaryGlow : AppColors.track)),
        child: InkWell(
          onTap: onTap,
          customBorder: const StadiumBorder(),
          child: Container(
            height: 46,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            alignment: Alignment.center,
            child: Text(
              label,
              style: TextStyle(fontSize: 16, color: selected ? AppColors.primary : AppColors.text),
            ),
          ),
        ),
      ),
    );
  }
}
