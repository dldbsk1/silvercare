import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../home/home_api.dart';
import '../../records/records_api.dart';
import '../family_api.dart';
import '../widgets/family_widgets.dart';
import '../widgets/parent_edit_sheet.dart';
import 'member_detail_screen.dart';

/// 초대 링크 공유 (테스트용 교체). 기본: 휴대폰 공유창 (카카오톡 선택)
typedef ShareInvite = Future<void> Function(String text);

Future<void> _systemShare(String text) =>
    SharePlus.instance.share(ShareParams(text: text));

/// SCR_A_300 가족
/// - 부모님 카드 / 구성원 (역할 배지, 최근 30일 기록 수) / 초대 대기
/// - 관리자만: 가족 초대하기 · 초대 다시 보내기
/// - 구성원 누름 → 구성원 정보 (권한·내보내기·관리자 넘기기)
class FamilyScreen extends StatefulWidget {
  const FamilyScreen({super.key, this.familyApi, this.authApi, this.recordsApi, this.share});

  /// 테스트용 교체
  final FamilyApi? familyApi;
  final AuthApi? authApi;
  final RecordsApi? recordsApi;
  final ShareInvite? share;

  @override
  State<FamilyScreen> createState() => _FamilyScreenState();
}

class _FamilyScreenState extends State<FamilyScreen> {
  late final FamilyApi _api = widget.familyApi ?? FamilyApi();
  late final AuthApi _auth = widget.authApi ?? AuthApi();
  late final ShareInvite _share = widget.share ?? _systemShare;

  String? _parentId;
  ParentInfo? _parent;
  List<FamilyMember> _members = [];

  /// userId → 최근 30일 기록 수 (실패 → 없음)
  Map<String, int> _counts = {};
  List<Invite> _invites = [];

  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    recordsChanged.addListener(_loadCounts);
    _load();
  }

  @override
  void dispose() {
    recordsChanged.removeListener(_loadCounts);
    super.dispose();
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  // ── 불러오기 ──

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final parentId = _parentId ??= await _loadParentId();
      final results = await Future.wait([
        _api.fetchParent(parentId),
        _api.fetchMembers(parentId),
      ]);
      final parent = results[0] as ParentInfo;
      final invites = parent.isAdmin
          ? await _api.fetchInvites(parentId)
          : <Invite>[];
      if (!mounted) return;
      setState(() {
        _parent = parent;
        _members = _sorted(results[1] as List<FamilyMember>);
        _invites = invites;
        _loading = false;
      });
      _loadCounts();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (_parent == null) _error = e.message;
      });
      if (_parent != null) _toast(e.message);
    }
  }

  Future<String> _loadParentId() async {
    final me = await _auth.fetchMe();
    if (me.parentIds.isEmpty) {
      throw ApiException(
        statusCode: 0,
        code: 'NO_PARENT',
        message: '등록된 부모님이 없어요.',
      );
    }
    return me.parentIds.first;
  }

  /// 나 → 관리자 → 기록 → 보기
  static List<FamilyMember> _sorted(List<FamilyMember> members) {
    const order = {'admin': 0, 'writer': 1, 'viewer': 2};
    return [...members]..sort((a, b) {
      if (a.isMe != b.isMe) return a.isMe ? -1 : 1;
      return (order[a.role] ?? 3).compareTo(order[b.role] ?? 3);
    });
  }

  /// 구성원별 기록 수 (각각 따로, 실패한 사람만 "-")
  Future<void> _loadCounts() async {
    final parentId = _parentId;
    if (parentId == null) return;
    final entries = await Future.wait(
      _members.map((m) async {
        try {
          return MapEntry(
            m.userId,
            await _api.countRecentRecords(parentId, m.userId),
          );
        } on ApiException {
          return null;
        }
      }),
    );
    if (!mounted) return;
    setState(
      () => _counts = {for (final e in entries.nonNulls) e.key: e.value},
    );
  }

  // ── 초대 ──

  Future<void> _openInviteSheet() async {
    await showFamilySheet<void>(
      context,
      (_) => _InviteSheet(
        create: () => _api.createInvite(_parentId!),
        share: (url) => _share(_inviteText(url)),
      ),
    );
    _load();
  }

  String _inviteText(String url) =>
      '${_parent?.nickname ?? '부모님'} 기록을 함께 남겨요. DAMA 초대 링크 (7일)\n$url';

  /// 링크 원문은 다시 못 받음 → 이전 초대 취소 + 같은 권한으로 새 초대 → 공유
  Future<void> _resend(Invite invite) async {
    try {
      final created = await _api.createInvite(_parentId!, role: invite.role);
      await _api.revokeInvite(invite.id);
      await _share(_inviteText(created.url));
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    }
    _load();
  }

  // ── 부모님 정보 ──

  /// 관리자만 수정. 나머지 → 안내
  Future<void> _editParent() async {
    final parent = _parent!;
    if (!parent.isAdmin) {
      _toast('부모님 정보는 관리자만 바꿀 수 있어요.');
      return;
    }
    final edit = await showFamilySheet<ParentEdit>(context, (_) => ParentEditSheet(parent: parent));
    if (edit == null) return;
    try {
      final updated = await _api.updateParent(parent.id, edit);
      if (mounted) setState(() => _parent = updated);
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    }
  }

  // ── 구성원 정보 ──

  /// 누구나 열람. 관리 기능(권한·내보내기·관리자 넘기기)은 화면 안에서 관리자만
  Future<void> _openMember(FamilyMember member) async {
    final me = _members.where((m) => m.isMe).firstOrNull;
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => MemberDetailScreen(
          parentId: _parentId!,
          member: member,
          me: me,
          familyApi: _api,
          recordsApi: widget.recordsApi,
        ),
      ),
    );
    if (changed == true) _load();
  }

  // ── 화면 ──

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
            ? _ErrorView(message: _error!, onRetry: _load)
            : RefreshIndicator(onRefresh: _load, child: _body()),
      ),
    );
  }

  Widget _body() {
    final parent = _parent!;
    final isAdmin = parent.isAdmin;
    final now = DateTime.now();
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
      children: [
        const Text(
          '가족',
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.text,
          ),
        ),
        const SizedBox(height: 16),
        _ParentCard(parent: parent, onTap: _editParent),
        const SizedBox(height: 24),
        Row(
          children: [
            Text(
              '구성원 ${_members.length}명',
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.text,
              ),
            ),
            const Spacer(),
            const Text(
              '최근 30일 기록',
              style: TextStyle(fontSize: 16, color: AppColors.subtext),
            ),
          ],
        ),
        const SizedBox(height: 12),
        for (final m in _members) ...[
          _MemberCard(
            member: m,
            count: _counts[m.userId],
            onTap: () => _openMember(m),
          ),
          const SizedBox(height: 8),
        ],
        if (isAdmin)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: _openInviteSheet,
              style: TextButton.styleFrom(
                foregroundColor: AppColors.primaryGlow,
                textStyle: const TextStyle(fontSize: 16),
              ),
              icon: const Icon(Icons.add, size: 22),
              label: const Text('가족 초대하기'),
            ),
          ),
        if (isAdmin && _invites.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text(
            '초대 대기',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 12),
          for (final invite in _invites) ...[
            _InviteCard(
              invite: invite,
              daysLeft: invite.daysLeft(now),
              onResend: () => _resend(invite),
            ),
            const SizedBox(height: 8),
          ],
        ],
        const SizedBox(height: 12),
        FilledButton(
          onPressed: () => _toast('체크리스트 보내기는 준비 중이에요.'),
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.primaryGlow,
            foregroundColor: Colors.white,
            minimumSize: const Size.fromHeight(52),
            shape: const StadiumBorder(),
            textStyle: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          child: const Text('체크리스트 보내기'),
        ),
      ],
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            message,
            style: const TextStyle(fontSize: 16, color: AppColors.subtext),
          ),
          const SizedBox(height: 12),
          TextButton(onPressed: onRetry, child: const Text('다시 시도')),
        ],
      ),
    );
  }
}

/// 부모님 카드 (Figma: 진녹색 그라데이션, 부모님 / 엄마 > / [80대] [조사대기], 오른쪽 사람 원)
class _ParentCard extends StatelessWidget {
  const _ParentCard({required this.parent, required this.onTap});

  final ParentInfo parent;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final tags = [
      if (parent.ageBand != null)
        ageBandLabels[parent.ageBand] ?? parent.ageBand!,
      applyStageLabels[parent.applyStage] ?? parent.applyStage,
    ];
    return Material(
      borderRadius: BorderRadius.circular(28),
      clipBehavior: Clip.antiAlias,
      child: Ink(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [AppColors.primary, AppColors.primaryGlow],
          ),
        ),
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(24, 20, 20, 20),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '부모님',
                        style: TextStyle(
                          fontSize: 15,
                          color: Color(0xE6FFFFFF),
                        ),
                      ),
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          Flexible(
                            child: Text(
                              parent.nickname,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 24,
                                fontWeight: FontWeight.w700,
                                color: Colors.white,
                              ),
                            ),
                          ),
                          const SizedBox(width: 6),
                          const Icon(
                            Icons.chevron_right,
                            size: 28,
                            color: Colors.white,
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          for (final tag in tags)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: AppColors.mint,
                                borderRadius: BorderRadius.circular(14),
                              ),
                              child: Text(
                                tag,
                                style: const TextStyle(
                                  fontSize: 16,
                                  color: AppColors.primary,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Container(
                  width: 80,
                  height: 80,
                  decoration: const BoxDecoration(
                    color: Color(0x40FFFFFF),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.person_outline,
                    size: 40,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 구성원 한 장 (Figma: 이름 첫 글자 원 / 이름 + 역할 배지 / 기록 수)
class _MemberCard extends StatelessWidget {
  const _MemberCard({
    required this.member,
    required this.count,
    required this.onTap,
  });

  final FamilyMember member;
  final int? count;

  /// 구성원 정보 열기
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final label = member.label;
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(10, 8, 20, 8),
          child: Row(
            children: [
              MemberAvatar(text: label.characters.first),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 2),
                    OutlineBadge(roleLabels[member.role] ?? member.role),
                  ],
                ),
              ),
              Text(
                count == null ? '-' : '$count건',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.subtext,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 초대 대기 한 장 (Figma: 점선 원 / 권한 + 남은 날 / 다시 보내기)
/// 초대받을 사람 이름은 서버에 없음 (링크만) → 권한으로 표시
class _InviteCard extends StatelessWidget {
  const _InviteCard({
    required this.invite,
    required this.daysLeft,
    required this.onResend,
  });

  final Invite invite;
  final int daysLeft;
  final VoidCallback onResend;

  @override
  Widget build(BuildContext context) {
    final title = invite.role == 'viewer' ? '보기만 초대' : '기록 가능 초대';
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 16, 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        children: [
          const MemberAvatar(text: '초', dashed: true),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
                Text(
                  daysLeft <= 0 ? '오늘 만료' : '$daysLeft일 남음',
                  style: const TextStyle(
                    fontSize: 16,
                    color: AppColors.subtext,
                  ),
                ),
              ],
            ),
          ),
          OutlinedButton(
            onPressed: onResend,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.primary,
              side: const BorderSide(color: AppColors.primary),
              minimumSize: const Size(0, 44),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              shape: const StadiumBorder(),
              textStyle: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
              ),
            ),
            child: const Text('다시 보내기'),
          ),
        ],
      ),
    );
  }
}

/// 가족 초대하기 시트 (Figma: 카톡으로 초대 / 링크 복사)
/// 초대 링크 = 부모님 건강 기록 공유 → 부모님(대리인) 동의 확인 체크 필요 (서버 share_confirmed)
class _InviteSheet extends StatefulWidget {
  const _InviteSheet({required this.create, required this.share});

  final Future<CreatedInvite> Function() create;
  final Future<void> Function(String url) share;

  @override
  State<_InviteSheet> createState() => _InviteSheetState();
}

class _InviteSheetState extends State<_InviteSheet> {
  bool _confirmed = false;
  bool _busy = false;

  /// 시트 안에서 한 번만 생성 (공유 + 복사 → 같은 링크)
  CreatedInvite? _invite;

  Future<String?> _url() async {
    if (_invite != null) return _invite!.url;
    try {
      _invite = await widget.create();
      return _invite!.url;
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
      return null;
    }
  }

  Future<void> _run(Future<void> Function(String url) action) async {
    setState(() => _busy = true);
    final url = await _url();
    if (url != null) await action(url);
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _copy(String url) async {
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('초대 링크를 복사했어요.')));
  }

  @override
  Widget build(BuildContext context) {
    final enabled = _confirmed && !_busy;
    return SheetFrame(
      title: '가족 초대하기',
      children: [
        const SizedBox(height: 4),
        const Text(
          '초대 링크는 7일 동안 쓸 수 있어요',
          style: TextStyle(fontSize: 16, color: AppColors.subtext),
        ),
        const SizedBox(height: 12),
        CheckboxListTile(
          value: _confirmed,
          onChanged: (v) => setState(() => _confirmed = v ?? false),
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          activeColor: AppColors.primaryGlow,
          title: const Text(
            '부모님께 가족과 기록을 함께 보는 것에 동의를 받았어요',
            style: TextStyle(fontSize: 16, color: AppColors.text),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: enabled ? () => _run(widget.share) : null,
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.primaryGlow,
            foregroundColor: Colors.white,
            disabledBackgroundColor: AppColors.track,
            minimumSize: const Size.fromHeight(52),
            shape: const StadiumBorder(),
            textStyle: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          child: const Text('초대 링크 공유'),
        ),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: enabled ? () => _run(_copy) : null,
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.primary,
            side: BorderSide(
              color: enabled ? AppColors.primaryGlow : AppColors.track,
            ),
            minimumSize: const Size.fromHeight(52),
            shape: const StadiumBorder(),
            textStyle: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          child: const Text('링크 복사'),
        ),
        const SizedBox(height: 16),
        const Text(
          '초대받은 사람도 동의가 필요해요',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 16, color: AppColors.subtext),
        ),
      ],
    );
  }
}

