import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../family/family_api.dart';
import '../../home/home_api.dart';
import '../checklist_api.dart';
import '../widgets/checklist_widgets.dart';
import 'checklist_answer_screen.dart';
import 'checklist_detail_screen.dart';

const _maxItems = 10;
const _maxDueDays = 30;
const _defaultDueDays = 7;

/// SCR_A_310 관찰 체크리스트 (가족 탭 안)
/// - 보내기: 추천 [이대로 쓰기] → 영역별 항목 고르기 → 받을 사람·확인 날짜 → 보내기 / 보낸 체크리스트
/// - 받은 체크리스트: 카드 [이어서 하기] → 답하기
class ChecklistScreen extends StatefulWidget {
  const ChecklistScreen({
    super.key,
    required this.parentId,
    this.initialTab = 0,
    this.api,
    this.familyApi,
    this.now,
  });

  final String parentId;

  /// 0 보내기 · 1 받은 체크리스트
  final int initialTab;

  /// 테스트용 교체
  final ChecklistApi? api;
  final FamilyApi? familyApi;
  final DateTime Function()? now;

  @override
  State<ChecklistScreen> createState() => _ChecklistScreenState();
}

class _ChecklistScreenState extends State<ChecklistScreen> {
  late final ChecklistApi _api = widget.api ?? ChecklistApi();
  late final FamilyApi _familyApi = widget.familyApi ?? FamilyApi();
  late int _tab = widget.initialTab;

  DateTime get _now => widget.now?.call() ?? DateTime.now();

  ChecklistDraft? _draft;
  List<FamilyMember> _recipients = [];
  List<Checklist> _sent = [];
  List<Checklist> _received = [];
  int _receivedTotal = 0;

  final Set<String> _selected = {};
  final Set<String> _expanded = {};
  String? _toUserId;
  late DateTime _dueDate = _today.add(const Duration(days: _defaultDueDays));
  String _idempotencyKey = HomeApi.newIdempotencyKey();

  bool _loading = true;
  bool _sending = false;
  String? _error;

  DateTime get _today => DateTime(_now.year, _now.month, _now.day);

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final results = await Future.wait([
        _api.fetchDraft(widget.parentId),
        _familyApi.fetchMembers(widget.parentId),
        _api.fetchList(widget.parentId, box: 'sent', state: 'all'),
        _api.fetchList(widget.parentId, box: 'received', state: 'open'),
      ]);
      if (!mounted) return;
      final received = results[3] as ChecklistPage;
      setState(() {
        _draft = results[0] as ChecklistDraft;
        _recipients = [
          for (final m in results[1] as List<FamilyMember>)
            if (m.role != 'viewer') m,
        ]..sort((a, b) => (a.isMe ? 0 : 1).compareTo(b.isMe ? 0 : 1));
        _sent = (results[2] as ChecklistPage).items;
        _received = received.items;
        _receivedTotal = received.total;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.message;
      });
    }
  }

  Future<void> _reloadLists() async {
    try {
      final results = await Future.wait([
        _api.fetchList(widget.parentId, box: 'sent', state: 'all'),
        _api.fetchList(widget.parentId, box: 'received', state: 'open'),
        _api.fetchDraft(widget.parentId),
      ]);
      if (!mounted) return;
      final received = results[1] as ChecklistPage;
      setState(() {
        _sent = (results[0] as ChecklistPage).items;
        _received = received.items;
        _receivedTotal = received.total;
        _draft = results[2] as ChecklistDraft;
      });
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    }
  }

  // ── 보내기 ──

  bool get _canSend => _selected.isNotEmpty && _selected.length <= _maxItems && _toUserId != null && !_sending;

  void _useSuggested() {
    final draft = _draft;
    if (draft == null) return;
    setState(() {
      _selected
        ..clear()
        ..addAll(draft.suggestedCodes);
      for (final area in draft.areas) {
        if (area.items.any((i) => draft.suggestedCodes.contains(i.code))) _expanded.add(area.area);
      }
    });
  }

  void _toggle(String code) {
    setState(() {
      if (_selected.contains(code)) {
        _selected.remove(code);
      } else if (_selected.length >= _maxItems) {
        _toast('한 번에 $_maxItems개까지 보낼 수 있어요.');
      } else {
        _selected.add(code);
      }
    });
  }

  Future<void> _pickRecipient() async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: Colors.white,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 20, 20, 8),
              child: Text('받을 사람', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
            ),
            for (final m in _recipients)
              ListTile(
                minTileHeight: 52,
                title: Text(m.label, style: const TextStyle(fontSize: 17)),
                trailing: m.userId == _toUserId ? const Icon(Icons.check, color: AppColors.primary) : null,
                onTap: () => Navigator.of(context).pop(m.userId),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (picked != null) setState(() => _toUserId = picked);
  }

  Future<void> _pickDate() async {
    var chosen = _dueDate;
    final picked = await showModalBottomSheet<DateTime>(
      context: context,
      backgroundColor: Colors.white,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('확인 날짜', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
              CalendarDatePicker(
                initialDate: _dueDate,
                firstDate: _today,
                lastDate: _today.add(const Duration(days: _maxDueDays)),
                onDateChanged: (d) => chosen = d,
              ),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => Navigator.of(context).pop(),
                      style: OutlinedButton.styleFrom(shape: const StadiumBorder()),
                      child: const Text('취소'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                      onPressed: () => Navigator.of(context).pop(chosen),
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.primaryGlow,
                        shape: const StadiumBorder(),
                      ),
                      child: const Text('선택'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
    if (picked != null) setState(() => _dueDate = picked);
  }

  Future<void> _send() async {
    final draft = _draft;
    final to = _toUserId;
    if (draft == null || to == null) return;
    // 조사표 순서로 보냄
    final codes = [
      for (final area in draft.areas)
        for (final item in area.items)
          if (_selected.contains(item.code)) item.code,
    ];
    setState(() => _sending = true);
    try {
      await _api.create(
        widget.parentId,
        toUserId: to,
        itemCodes: codes,
        dueDate: _dueDate,
        idempotencyKey: _idempotencyKey,
      );
      if (!mounted) return;
      _idempotencyKey = HomeApi.newIdempotencyKey();
      setState(() {
        _selected.clear();
        _toUserId = null;
      });
      _toast('체크리스트를 보냈어요.');
      await _reloadLists();
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  // ── 열기 ──

  Future<void> _openAnswer(Checklist summary) async {
    try {
      final checklist = await _api.fetch(summary.id);
      if (!mounted) return;
      if (!checklist.isOpen) {
        _toast(checklist.status == 'cancelled' ? '취소된 체크리스트예요.' : '이미 보낸 체크리스트예요.');
        await _reloadLists();
        return;
      }
      await Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => ChecklistAnswerScreen(checklist: checklist, api: _api)),
      );
      await _reloadLists();
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    }
  }

  Future<void> _openSent(Checklist summary) async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ChecklistDetailScreen(checklistId: summary.id, api: _api)),
    );
    await _reloadLists();
  }

  // ── 화면 ──

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        titleSpacing: 0,
        title: const Text(
          '관찰 체크리스트',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(_error!, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
                      TextButton(onPressed: _load, child: const Text('다시 시도')),
                    ],
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
                  children: [
                    _tabs(),
                    const SizedBox(height: 16),
                    if (_tab == 0) ..._sendTab() else ..._receivedTab(),
                  ],
                ),
    );
  }

  Widget _tabs() {
    Widget tab(int index, String label, {int? badge}) {
      final selected = _tab == index;
      return Expanded(
        child: GestureDetector(
          onTap: () => setState(() => _tab = index),
          child: Container(
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: selected ? AppColors.primary : Colors.transparent,
              borderRadius: BorderRadius.circular(22),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: selected ? Colors.white : AppColors.text,
                  ),
                ),
                if (badge != null && badge > 0) ...[
                  const SizedBox(width: 6),
                  CircleAvatar(
                    radius: 11,
                    backgroundColor: selected ? Colors.white : AppColors.primaryGlow,
                    child: Text(
                      '$badge',
                      style: TextStyle(fontSize: 13, color: selected ? AppColors.primary : Colors.white),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: AppColors.mint, borderRadius: BorderRadius.circular(26)),
      child: Row(children: [tab(0, '보내기'), tab(1, '받은 체크리스트', badge: _receivedTotal)]),
    );
  }

  List<Widget> _sendTab() {
    final draft = _draft!;
    final selectedOf = {
      for (final area in draft.areas) area.area: area.items.where((i) => _selected.contains(i.code)).length,
    };
    final recipient = _recipients.where((m) => m.userId == _toUserId).firstOrNull;
    return [
      if (draft.suggestedCodes.isNotEmpty) ...[
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: AppColors.mint, borderRadius: BorderRadius.circular(16)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '기록이 부족한 ${draft.suggestedCodes.length}개 항목으로 만들었어요',
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _useSuggested,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.primaryGlow,
                  shape: const StadiumBorder(),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                child: const Text('이대로 쓰기'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
      ],
      const _SectionTitle('항목 고르기'),
      for (final area in draft.areas) ...[
        _areaTile(area, selectedOf[area.area] ?? 0),
        const SizedBox(height: 8),
      ],
      const SizedBox(height: 12),
      const _SectionTitle('보낼 설정'),
      WhiteCard(
        padding: EdgeInsets.zero,
        child: Column(
          children: [
            _settingRow('받을 사람', recipient?.label ?? '선택', _pickRecipient),
            const Divider(height: 1, indent: 16, endIndent: 16, color: AppColors.border),
            _settingRow('확인 날짜', shortDate(_dueDate), _pickDate),
          ],
        ),
      ),
      const SizedBox(height: 16),
      FilledButton(
        onPressed: _canSend ? _send : null,
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primaryGlow,
          disabledBackgroundColor: AppColors.track,
          minimumSize: const Size.fromHeight(52),
          shape: const StadiumBorder(),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        ),
        child: Text(
          _selected.isEmpty ? '체크리스트 보내기' : '체크리스트 보내기 · ${_selected.length}개 항목',
        ),
      ),
      const SizedBox(height: 24),
      const _SectionTitle('보낸 체크리스트'),
      if (_sent.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: Text('아직 보낸 체크리스트가 없어요', style: TextStyle(fontSize: 16, color: AppColors.subtext)),
        ),
      for (final c in _sent) ...[
        _SentRow(checklist: c, onTap: () => _openSent(c)),
        const SizedBox(height: 8),
      ],
    ];
  }

  Widget _areaTile(DraftArea area, int selectedCount) {
    final open = _expanded.contains(area.area);
    return WhiteCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: () => setState(() => open ? _expanded.remove(area.area) : _expanded.add(area.area)),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: Row(
                children: [
                  Text(area.label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  Text(' · $selectedCount개 선택', style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                  const Spacer(),
                  Icon(open ? Icons.expand_less : Icons.expand_more, color: AppColors.text),
                ],
              ),
            ),
          ),
          if (open)
            for (final item in area.items) _itemRow(item),
        ],
      ),
    );
  }

  Widget _itemRow(DraftItem item) {
    final last = item.lastRecordedOn;
    return InkWell(
      onTap: () => _toggle(item.code),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 4, 16, 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Checkbox(
              value: _selected.contains(item.code),
              onChanged: (_) => _toggle(item.code),
              activeColor: AppColors.primaryGlow,
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(item.label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                    Text(item.hint, style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                    Text(
                      last == null ? '기록 없음' : '마지막 기록 ${last.month}/${last.day}',
                      style: const TextStyle(fontSize: 15, color: AppColors.subtext),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _settingRow(String label, String value, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            Text(label, style: const TextStyle(fontSize: 16, color: AppColors.text)),
            const Spacer(),
            Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            const Icon(Icons.chevron_right, color: AppColors.text),
          ],
        ),
      ),
    );
  }

  List<Widget> _receivedTab() {
    if (_received.isEmpty) {
      return const [
        Padding(
          padding: EdgeInsets.symmetric(vertical: 40),
          child: Text(
            '받은 체크리스트가 없어요',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, color: AppColors.subtext),
          ),
        ),
      ];
    }
    return [
      for (final c in _received) ...[
        ReceivedCard(checklist: c, now: _now, onContinue: () => _openAnswer(c)),
        const SizedBox(height: 12),
      ],
    ];
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text)),
    );
  }
}

/// "형 · 11/5 / 3/4 진행 / 대기"
class _SentRow extends StatelessWidget {
  const _SentRow({required this.checklist, required this.onTap});

  final Checklist checklist;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final due = checklist.dueDate;
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${checklist.to.label} · ${due.month}/${due.day}',
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    Text(
                      '${checklist.answeredItems}/${checklist.totalItems} 진행',
                      style: const TextStyle(fontSize: 15, color: AppColors.subtext),
                    ),
                  ],
                ),
              ),
              StatusBadge(status: checklist.status),
            ],
          ),
        ),
      ),
    );
  }
}
