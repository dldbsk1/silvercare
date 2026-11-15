import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../home/home_api.dart';
import '../../records/records_api.dart';
import '../../records/widgets/record_card.dart';
import '../family_api.dart';
import '../widgets/family_widgets.dart';

/// 구성원 정보 (가족 탭 → 구성원 누름)
/// - 누구나: 역할 · 함께한 날 · 기록 수 (30일 / 전체) · 최근 기록 3건
/// - 관리자 → 다른 구성원: 권한 바꾸기 · 관리자 넘기기 (따로) · 내보내기
/// - 나: 가족에서 나가기
/// 돌아갈 때 바뀐 것 있음 → true (가족 화면 새로고침)
class MemberDetailScreen extends StatefulWidget {
  const MemberDetailScreen({
    super.key,
    required this.parentId,
    required this.member,
    required this.me,
    this.familyApi,
    this.recordsApi,
  });

  final String parentId;
  final FamilyMember member;

  /// 내 구성원 정보 (관리자 여부 · 넘기기용 member id)
  final FamilyMember? me;

  /// 테스트용 교체
  final FamilyApi? familyApi;
  final RecordsApi? recordsApi;

  @override
  State<MemberDetailScreen> createState() => _MemberDetailScreenState();
}

class _MemberDetailScreenState extends State<MemberDetailScreen> {
  late final FamilyApi _api = widget.familyApi ?? FamilyApi();
  late final RecordsApi _records = widget.recordsApi ?? RecordsApi();

  late FamilyMember _member = widget.member;
  late FamilyMember? _me = widget.me;

  int? _recentCount;
  int? _totalCount;
  List<RecordSummary> _recent = [];
  bool _recordsLoading = true;
  bool _busy = false;
  bool _changed = false;

  bool get _iAmAdmin => _me?.role == 'admin';
  bool get _isMe => _member.isMe;
  bool get _canManage => _iAmAdmin && !_isMe;

  @override
  void initState() {
    super.initState();
    _loadRecords();
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _loadRecords() async {
    try {
      final results = await Future.wait([
        _records.listRecords(
          widget.parentId,
          RecordFilter(authorId: _member.userId, period: RecordPeriod.all),
          limit: 3,
        ),
        _api.countRecentRecords(widget.parentId, _member.userId),
      ]);
      if (!mounted) return;
      final page = results[0] as RecordPage;
      setState(() {
        _recent = page.records;
        _totalCount = page.total;
        _recentCount = results[1] as int;
        _recordsLoading = false;
      });
    } on ApiException {
      if (mounted) setState(() => _recordsLoading = false);
    }
  }

  FamilyMember _withRole(FamilyMember m, String role) => FamilyMember(
        memberId: m.memberId,
        userId: m.userId,
        displayName: m.displayName,
        role: role,
        isMe: m.isMe,
        joinedAt: m.joinedAt,
      );

  /// 진행 중 버튼 잠금 + 오류 안내
  Future<bool> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
      _changed = true;
      return true;
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ── 관리 ──

  Future<void> _changeRole() async {
    final role = await showFamilySheet<String>(
      context,
      (_) => RoleSheet(name: _member.name, current: _member.role),
    );
    if (role == null || role == _member.role) return;
    final ok = await _run(() => _api.changeRole(_member.memberId, role));
    if (!ok || !mounted) return;
    setState(() => _member = _withRole(_member, role));
    _toast('${_member.name}의 권한을 바꿨어요.');
  }

  Future<void> _transferAdmin() async {
    final me = _me;
    if (me == null) return;
    final yes = await _confirm(
      title: '${_member.name}에게 관리자를 넘길까요?',
      body: '넘기면 나는 \'기록 가능\'으로 바뀌어요.\n가족 초대 · 권한 · 부모님 정보는 ${_member.name}만 바꿀 수 있어요.\n내가 만든 초대 링크는 취소돼요.',
      action: '넘기기',
    );
    if (!yes) return;
    final ok = await _run(() => _api.transferAdmin(_member.memberId));
    if (!ok || !mounted) return;
    setState(() {
      _member = _withRole(_member, 'admin');
      _me = _withRole(me, 'writer');
    });
    _toast('${_member.name}에게 관리자를 넘겼어요.');
  }

  Future<void> _remove() async {
    final yes = await _confirm(
      title: _isMe ? '가족에서 나갈까요?' : '${_member.name}을(를) 가족에서 내보낼까요?',
      body: _isMe
          ? '나가면 부모님 기록을 더 볼 수 없어요.\n내가 남긴 기록은 가족에게 그대로 남아요.'
          : '${_member.name}은(는) 더 이상 기록을 볼 수 없어요.\n${_member.name}이(가) 남긴 기록은 그대로 남아요.',
      action: _isMe ? '나가기' : '내보내기',
      destructive: true,
    );
    if (!yes) return;
    final ok = await _run(() => _api.removeMember(_member.memberId));
    if (!ok || !mounted) return;
    if (_isMe) {
      // 이 부모님 가족 X → 처음부터 다시 분기 (다른 가족 / 부모님 등록)
      context.go('/');
    } else {
      _toast('${_member.name}을(를) 내보냈어요.');
      Navigator.of(context).pop(true);
    }
  }

  Future<bool> _confirm({
    required String title,
    required String body,
    required String action,
    bool destructive = false,
  }) async {
    final error = Theme.of(context).colorScheme.error;
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: Colors.white,
        title: Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text)),
        content: Text(body, style: const TextStyle(fontSize: 16, color: AppColors.subtext, height: 1.5)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            style: TextButton.styleFrom(foregroundColor: AppColors.subtext, minimumSize: const Size(64, 44)),
            child: const Text('취소', style: TextStyle(fontSize: 16)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(
              backgroundColor: destructive ? error : AppColors.primaryGlow,
              minimumSize: const Size(80, 44),
              shape: const StadiumBorder(),
            ),
            child: Text(action, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
    return result ?? false;
  }

  // ── 화면 ──

  @override
  Widget build(BuildContext context) {
    return PopScope<bool>(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.of(context).pop(_changed);
      },
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          backgroundColor: AppColors.background,
          surfaceTintColor: Colors.transparent,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: '뒤로',
            onPressed: () => Navigator.of(context).pop(_changed),
          ),
          title: const Text(
            '구성원 정보',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
          ),
        ),
        body: AbsorbPointer(
          absorbing: _busy,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
            children: [
              _profile(),
              const SizedBox(height: 12),
              _stats(),
              const SizedBox(height: 24),
              const _SectionTitle('최근 기록'),
              const SizedBox(height: 12),
              ..._recentRecords(),
              if (_canManage) ...[
                const SizedBox(height: 28),
                const _SectionTitle('권한'),
                const SizedBox(height: 12),
                _roleCard(),
                if (_member.role != 'admin') ...[
                  const SizedBox(height: 28),
                  const _SectionTitle('관리자 넘기기'),
                  const SizedBox(height: 12),
                  _transferCard(),
                ],
              ],
              if (_canManage || _isMe) ...[
                const SizedBox(height: 28),
                Center(
                  child: TextButton(
                    onPressed: _remove,
                    style: TextButton.styleFrom(
                      foregroundColor: Theme.of(context).colorScheme.error,
                      minimumSize: const Size(0, 44),
                      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    child: Text(_isMe ? '가족에서 나가기' : '가족에서 내보내기'),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _profile() {
    final joined = _member.joinedAt;
    return _WhiteCard(
      child: Row(
        children: [
          MemberAvatar(text: _member.label.characters.first),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        _member.name,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
                      ),
                    ),
                    if (_isMe)
                      const Text(' (나)', style: TextStyle(fontSize: 16, color: AppColors.subtext)),
                    const SizedBox(width: 8),
                    OutlineBadge(roleLabels[_member.role] ?? _member.role),
                  ],
                ),
                if (joined != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    '${joined.year}년 ${joined.month}월 ${joined.day}일부터 함께해요',
                    style: const TextStyle(fontSize: 16, color: AppColors.subtext),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _stats() {
    String count(int? n) => _recordsLoading ? '…' : (n == null ? '-' : '$n건');
    final last = _recent.isEmpty ? null : _recent.first.recordedAt;
    return Row(
      children: [
        Expanded(child: _StatCard(label: '최근 30일', value: count(_recentCount))),
        const SizedBox(width: 8),
        Expanded(child: _StatCard(label: '전체 기록', value: count(_totalCount))),
        const SizedBox(width: 8),
        Expanded(
          child: _StatCard(
            label: '마지막 기록',
            value: _recordsLoading ? '…' : (last == null ? '없음' : '${last.month}/${last.day}'),
          ),
        ),
      ],
    );
  }

  List<Widget> _recentRecords() {
    if (_recordsLoading) {
      return const [Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))];
    }
    if (_recent.isEmpty) {
      return const [
        Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Text(
            '아직 남긴 기록이 없어요',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, color: AppColors.subtext),
          ),
        ),
      ];
    }
    return [
      for (final r in _recent) ...[RecordCard(record: r), const SizedBox(height: 8)],
    ];
  }

  Widget _roleCard() {
    const descriptions = {
      'admin': '가족 초대 · 권한 · 부모님 정보를 바꿀 수 있어요',
      'writer': '기록을 남기고 고칠 수 있어요',
      'viewer': '기록을 볼 수만 있어요',
    };
    return _WhiteCard(
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  const {'admin': '관리자', 'writer': '기록 가능', 'viewer': '보기만'}[_member.role] ?? _member.role,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
                ),
                const SizedBox(height: 2),
                Text(
                  descriptions[_member.role] ?? '',
                  style: const TextStyle(fontSize: 16, color: AppColors.subtext),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          _SmallOutlineButton(label: '바꾸기', onPressed: _changeRole),
        ],
      ),
    );
  }

  Widget _transferCard() {
    return _WhiteCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            '${_member.name}이(가) 관리자가 되고, 나는 \'기록 가능\'으로 바뀌어요.',
            style: const TextStyle(fontSize: 16, color: AppColors.subtext, height: 1.5),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: _transferAdmin,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.primary,
              side: const BorderSide(color: AppColors.primaryGlow),
              minimumSize: const Size.fromHeight(48),
              shape: const StadiumBorder(),
              textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            child: Text('${_member.name}에게 관리자 넘기기'),
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text));
  }
}

class _WhiteCard extends StatelessWidget {
  const _WhiteCard({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
      child: child,
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
      child: Column(
        children: [
          Text(label, style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.text)),
        ],
      ),
    );
  }
}

class _SmallOutlineButton extends StatelessWidget {
  const _SmallOutlineButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.primary,
        side: const BorderSide(color: AppColors.primary),
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 16),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: Text(label),
    );
  }
}
