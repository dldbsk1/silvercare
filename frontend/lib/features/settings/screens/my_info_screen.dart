import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../../core/auth/me.dart';
import '../../../core/push/push_service.dart';
import '../../family/family_api.dart';
import '../../family/widgets/family_widgets.dart';
import '../../family/widgets/parent_edit_sheet.dart';
import '../../onboarding/consent_api.dart';
import '../settings_api.dart';
import '../widgets/data_choice_dialog.dart';

/// SCR_A_500 내 정보
/// - 로그인 방식 · 부모님 카드 (관리자: 수정) · PC에서 열기
/// - 알림 (컨디션 · 할 일 · 브리핑) · 동의 관리 (철회 / 알림 동의)
/// - 기록 공간 삭제 (관리자 요청 → 관리자 전원 동의 → 7일 유예 → 삭제. 관리자 누구나 취소)
/// - 로그아웃 · 탈퇴
class MyInfoScreen extends StatefulWidget {
  const MyInfoScreen({super.key, this.settingsApi, this.familyApi, this.authApi, this.consentApi});

  /// 테스트용 교체
  final SettingsApi? settingsApi;
  final FamilyApi? familyApi;
  final AuthApi? authApi;
  final ConsentApi? consentApi;

  @override
  State<MyInfoScreen> createState() => _MyInfoScreenState();
}

class _MyInfoScreenState extends State<MyInfoScreen> {
  late final SettingsApi _api = widget.settingsApi ?? SettingsApi();
  late final FamilyApi _family = widget.familyApi ?? FamilyApi();
  late final AuthApi _auth = widget.authApi ?? AuthApi();
  late final ConsentApi _consentApi = widget.consentApi ?? ConsentApi();

  Me? _me;
  ParentInfo? _parent;
  NotificationSettings? _noti;
  MyConsents? _consents;
  ParentDeletion? _deletion;

  bool _loading = true;
  bool _busy = false;
  String? _error;

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
      final me = await _auth.fetchMe();
      final parentId = me.parentIds.firstOrNull;
      final results = await Future.wait([
        _api.fetchNotifications(),
        _api.fetchConsents(),
        if (parentId != null) _family.fetchParent(parentId),
        if (parentId != null) _api.fetchDeletion(parentId),
      ]);
      if (!mounted) return;
      setState(() {
        _me = me;
        _noti = results[0] as NotificationSettings;
        _consents = results[1] as MyConsents;
        _parent = parentId == null ? null : results[2] as ParentInfo;
        _deletion = parentId == null ? null : results[3] as ParentDeletion?;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (_me == null) _error = e.message;
      });
      if (_me != null) _toast(e.message);
    }
  }

  /// 진행 중 잠금 + 오류 안내. 성공 → true
  Future<bool> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
      return true;
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ── 부모님 ──

  Future<void> _editParent() async {
    final parent = _parent!;
    final edit = await showFamilySheet<ParentEdit>(context, (_) => ParentEditSheet(parent: parent));
    if (edit == null) return;
    await _run(() async {
      final updated = await _family.updateParent(parent.id, edit);
      if (mounted) setState(() => _parent = updated);
    });
  }

  // ── 알림 ──

  Future<void> _toggle(NotificationSettings next) async {
    final before = _noti;
    setState(() => _noti = next);
    try {
      final saved = await _api.saveNotifications(next);
      if (mounted) setState(() => _noti = saved);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _noti = before);
      _toast(e.message);
    }
  }

  // ── 동의 ──

  Future<void> _revoke(String type) async {
    final required = requiredConsents.contains(type);
    var deleteMyRecords = false;
    if (required) {
      final due = DateTime.now().add(const Duration(days: 7));
      final choice = await showDataChoiceDialog(
        context,
        title: '${_shortLabel(type)} 동의를\n철회할까요?',
        notes: revokeNotes,
        deleteHelp: '7일 뒤(${_date(due)}) 삭제돼요. 그 전에 다시 동의하면 취소돼요.',
        action: '철회하기',
      );
      if (choice == null) return;
      deleteMyRecords = choice;
    } else {
      final yes = await showConfirmDialog(
        context,
        title: '알림 수신 동의를\n철회할까요?',
        body: '철회하면 알림을 받지 않아요. 언제든 다시 동의할 수 있어요.',
        action: '철회하기',
      );
      if (!yes) return;
    }
    final ok = await _run(() async {
      final consents = await _api.revokeConsent(type, deleteMyRecords: deleteMyRecords);
      if (mounted) setState(() => _consents = consents);
    });
    if (!ok || !mounted) return;
    if (required) {
      // 필수 동의 없음 → 동의 화면부터 (처음 분기)
      context.go('/');
    } else {
      _load();
    }
  }

  Future<void> _agreeNoti() async {
    final ok = await _run(() async {
      final docs = await _consentApi.fetchRequired();
      final noti = docs.where((d) => d.type == 'noti').toList();
      await _consentApi.save(noti, {'noti'});
    });
    if (ok) _load();
  }

  static String _shortLabel(String type) =>
      const {'service': '서비스 이용', 'privacy': '개인정보', 'health': '건강정보'}[type] ?? type;

  static String _date(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  // ── 기록 공간 삭제 ──

  Future<void> _requestDeletion() async {
    final parent = _parent!;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => _DeleteSpaceDialog(nickname: parent.nickname),
    );
    if (confirmed != true) return;
    await _run(() async {
      final deletion = await _api.requestDeletion(parent.id);
      if (!mounted) return;
      setState(() => _deletion = deletion);
      _toast(deletion.isPending ? '다른 관리자의 동의를 기다려요.' : '7일 뒤 삭제돼요. 그전에 취소할 수 있어요.');
    });
  }

  Future<void> _approveDeletion() async {
    final yes = await showConfirmDialog(
      context,
      title: '기록 공간 삭제에\n동의할까요?',
      body: '관리자가 모두 동의하면 7일 뒤 ${_parent!.nickname}의 모든 기록과 음성 파일이 삭제돼요. 그동안은 기록을 남길 수 없어요.',
      action: '동의하기',
      destructive: true,
    );
    if (!yes) return;
    await _run(() async {
      final deletion = await _api.approveDeletion(_parent!.id);
      if (mounted) setState(() => _deletion = deletion);
    });
  }

  Future<void> _cancelDeletion() async {
    final pending = _deletion?.isPending ?? false;
    final yes = await showConfirmDialog(
      context,
      title: pending ? '삭제 요청을 취소할까요?' : '삭제를 취소할까요?',
      body: '기록 공간이 그대로 남고, 다시 기록을 남길 수 있어요.',
      action: '취소하기',
      cancelLabel: '닫기',
    );
    if (!yes) return;
    final ok = await _run(() => _api.cancelDeletion(_parent!.id));
    if (ok && mounted) setState(() => _deletion = null);
  }

  // ── 로그아웃 · 탈퇴 ──

  Future<void> _logout() async {
    final yes = await showConfirmDialog(
      context,
      title: '로그아웃할까요?',
      body: '다시 로그인하면 기록을 이어서 볼 수 있어요.',
      action: '로그아웃',
    );
    if (!yes) return;
    await PushService.instance.unregister();
    await _auth.signOut();
    if (mounted) context.go('/');
  }

  /// 확인 (관리자 넘기기 필요 → 가족 탭 / 혼자 쓰는 공간 → 삭제 확인) → 데이터 처리 안내 + 기록 지우기 선택 → 탈퇴
  Future<void> _withdraw() async {
    List<WithdrawalParent>? parents;
    final checked = await _run(() async => parents = await _api.withdrawalCheck());
    if (!checked || !mounted) return;

    final needTransfer = parents!.where((p) => p.status == 'transfer_required').toList();
    if (needTransfer.isNotEmpty) {
      final go = await showConfirmDialog(
        context,
        title: '관리자를 먼저 넘겨 주세요',
        body: '${needTransfer.map((p) => p.nickname).join(', ')} 기록 공간의 관리자가 나뿐이에요. 가족 탭에서 구성원을 눌러 관리자를 넘겨 주세요.',
        action: '가족 탭으로',
        cancelLabel: '닫기',
      );
      if (go && mounted) context.go('/family');
      return;
    }

    final sole = parents!.where((p) => p.status == 'sole_member').toList();
    if (sole.isNotEmpty) {
      final yes = await showConfirmDialog(
        context,
        title: '기록 공간도 함께 삭제돼요',
        body: '${sole.map((p) => p.nickname).join(', ')} 기록 공간을 나 혼자 쓰고 있어요. 탈퇴하면 7일 뒤 이 공간의 모든 기록도 함께 삭제돼요.',
        action: '계속',
        destructive: true,
      );
      if (!yes || !mounted) return;
    }

    final deleteMyRecords = await showDataChoiceDialog(
      context,
      title: '정말 탈퇴할까요?',
      notes: withdrawalNotes,
      deleteHelp: '가족 공간에서도 사라지고, 되돌릴 수 없어요.',
      action: '탈퇴하기',
    );
    if (deleteMyRecords == null) return;

    final ok = await _run(
      () => _api.withdraw(deleteSoleParents: sole.isNotEmpty, deleteMyRecords: deleteMyRecords),
    );
    if (ok && mounted) context.go('/withdrawn');
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
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
                        TextButton(onPressed: _load, child: const Text('다시 시도')),
                      ],
                    ),
                  )
                : AbsorbPointer(
                    absorbing: _busy,
                    child: RefreshIndicator(onRefresh: _load, child: _body()),
                  ),
      ),
    );
  }

  Widget _body() {
    final parent = _parent;
    final deletion = _deletion;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        const Text('내 정보', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text)),
        const SizedBox(height: 16),
        _LoginCard(loginType: _me?.loginType, contact: _auth.contact),
        if (parent != null) ...[
          const SizedBox(height: 24),
          _ParentCard(parent: parent, onEdit: parent.isAdmin && deletion?.status != 'scheduled' ? _editParent : null),
        ],
        const SizedBox(height: 28),
        _OutlinedRow(
          icon: Icons.desktop_windows_outlined,
          label: 'PC에서 열기',
          bold: true,
          onTap: () => _toast('PC 화면은 준비 중이에요.'),
        ),
        const SizedBox(height: 16),
        const _SectionTitle('알림'),
        _notificationGroup(),
        const SizedBox(height: 24),
        const _SectionTitle('동의 관리'),
        _consentGroup(),
        const SizedBox(height: 24),
        _Group(children: [
          for (final label in ['고객센터', '이용약관', '개인정보처리방침'])
            _ChevronRow(label: label, onTap: () => _toast('$label 화면은 준비 중이에요.')),
        ]),
        if (parent != null && (parent.isAdmin || deletion != null)) ...[
          const SizedBox(height: 24),
          const _SectionTitle('기록 공간'),
          _DeletionCard(
            parent: parent,
            deletion: deletion,
            onRequest: _requestDeletion,
            onApprove: _approveDeletion,
            onCancel: _cancelDeletion,
          ),
        ],
        const SizedBox(height: 24),
        Row(
          children: [
            Expanded(child: _PillButton(label: '로그아웃', onPressed: _logout)),
            const SizedBox(width: 8),
            Expanded(child: _PillButton(label: '탈퇴', onPressed: _withdraw)),
          ],
        ),
      ],
    );
  }

  Widget _notificationGroup() {
    final noti = _noti!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Group(children: [
          _SwitchRow(label: '컨디션 알림', value: noti.condition, onChanged: (v) => _toggle(noti.copyWith(condition: v))),
          _SwitchRow(label: '할 일 알림', value: noti.tasks, onChanged: (v) => _toggle(noti.copyWith(tasks: v))),
          _SwitchRow(label: '브리핑 알림', value: noti.briefing, onChanged: (v) => _toggle(noti.copyWith(briefing: v))),
        ]),
        if (!noti.notiConsented)
          const Padding(
            padding: EdgeInsets.only(top: 8, left: 4),
            child: Text(
              '알림 수신 동의를 해야 알림이 와요',
              style: TextStyle(fontSize: 15, color: AppColors.subtext),
            ),
          ),
      ],
    );
  }

  Widget _consentGroup() {
    final current = _consents!.current;
    return _Group(children: [
      for (final e in consentLabels.entries)
        _ConsentRow(
          label: e.value,
          agreedAt: current[e.key]?.agreedAt,
          onRevoke: () => _revoke(e.key),
          // 선택 동의만 앱에서 다시 동의 (필수 → 동의 화면)
          onAgree: e.key == 'noti' ? _agreeNoti : null,
        ),
    ]);
  }
}

// ── 확인 창 (Figma: 흰 둥근 창, 제목 / 설명 / 취소 · 실행 알약 버튼) ──

Future<bool> showConfirmDialog(
  BuildContext context, {
  required String title,
  required String body,
  required String action,
  String cancelLabel = '취소',
  bool destructive = false,
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (context) => Dialog(
      backgroundColor: Colors.white,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: AppColors.text)),
            const SizedBox(height: 12),
            Text(body, style: const TextStyle(fontSize: 16, color: AppColors.subtext, height: 1.6)),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.text,
                      side: const BorderSide(color: AppColors.track),
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    child: Text(cancelLabel),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).pop(true),
                    style: FilledButton.styleFrom(
                      backgroundColor: destructive ? Theme.of(context).colorScheme.error : AppColors.primaryGlow,
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    child: Text(action),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
  return result ?? false;
}

/// 공간 삭제 확인: 경고 + 부모님 호칭 직접 입력해야 버튼 켜짐
class _DeleteSpaceDialog extends StatefulWidget {
  const _DeleteSpaceDialog({required this.nickname});

  final String nickname;

  @override
  State<_DeleteSpaceDialog> createState() => _DeleteSpaceDialogState();
}

class _DeleteSpaceDialogState extends State<_DeleteSpaceDialog> {
  final _input = TextEditingController();

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final error = Theme.of(context).colorScheme.error;
    final matches = _input.text.trim() == widget.nickname;
    return Dialog(
      backgroundColor: Colors.white,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${widget.nickname} 기록 공간을\n삭제할까요?',
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            const SizedBox(height: 12),
            const Text(
              '가족 모두가 남긴 기록 · 음성 파일 · 고친 이력이 모두 삭제되고 되돌릴 수 없어요.\n\n'
              '관리자가 여러 명이면 모두 동의해야 삭제가 예약돼요. 예약 뒤 7일 동안은 기록을 남길 수 없고, 관리자 누구나 취소할 수 있어요.',
              style: TextStyle(fontSize: 16, color: AppColors.subtext, height: 1.6),
            ),
            const SizedBox(height: 16),
            Text(
              '확인을 위해 "${widget.nickname}"을(를) 입력해 주세요',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _input,
              onChanged: (_) => setState(() {}),
              style: const TextStyle(fontSize: 16),
              decoration: InputDecoration(hintText: widget.nickname),
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.text,
                      side: const BorderSide(color: AppColors.track),
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                    ),
                    child: const Text('취소', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: matches ? () => Navigator.of(context).pop(true) : null,
                    style: FilledButton.styleFrom(
                      backgroundColor: error,
                      disabledBackgroundColor: AppColors.track,
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                    ),
                    child: const Text('삭제 요청', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ── 조각 위젯 ──

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text)),
      );
}

/// 흰 바탕 + 연한 테두리 묶음 (줄 사이 구분선)
class _Group extends StatelessWidget {
  const _Group({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.track),
      ),
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const Divider(height: 1, color: AppColors.track),
            children[i],
          ],
        ],
      ),
    );
  }
}

class _LoginCard extends StatelessWidget {
  const _LoginCard({required this.loginType, required this.contact});

  final String? loginType;
  final String? contact;

  static const _labels = {
    'kakao': '카카오 로그인',
    'naver': '네이버 로그인',
    'google': '구글 로그인',
    'phone': '휴대폰 번호 로그인',
    'email': '이메일 로그인',
  };

  @override
  Widget build(BuildContext context) {
    final (Color bg, Color fg, IconData icon) = switch (loginType) {
      'kakao' => (AppColors.kakao, Colors.black, Icons.chat_bubble),
      'naver' => (AppColors.naver, Colors.white, Icons.north_east),
      'google' => (Colors.white, AppColors.text, Icons.g_mobiledata),
      'email' => (AppColors.mint, AppColors.primary, Icons.mail_outline),
      _ => (AppColors.mint, AppColors.primary, Icons.phone_iphone),
    };
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.track),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(color: bg, shape: BoxShape.circle),
            child: Icon(icon, size: 20, color: fg),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _labels[loginType] ?? '로그인',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
                ),
                if (contact != null)
                  Text(contact!, style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Figma: 진녹색 카드 / 사람 원 + 호칭 + 수정 / [80대] [조사대기] [따로 살아요]
class _ParentCard extends StatelessWidget {
  const _ParentCard({required this.parent, required this.onEdit});

  final ParentInfo parent;

  /// 관리자만 (아니면 null → 버튼 숨김)
  final VoidCallback? onEdit;

  @override
  Widget build(BuildContext context) {
    final tags = [
      if (parent.ageBand != null) ageBandLabels[parent.ageBand] ?? parent.ageBand!,
      applyStageLabels[parent.applyStage] ?? parent.applyStage,
      parent.cohabiting ? '함께 살아요' : '따로 살아요',
    ];
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
      decoration: BoxDecoration(
        gradient: const LinearGradient(colors: [AppColors.primary, AppColors.primaryGlow]),
        borderRadius: BorderRadius.circular(28),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 60,
                height: 60,
                decoration: const BoxDecoration(color: AppColors.mint, shape: BoxShape.circle),
                child: const Icon(Icons.person_outline, size: 32, color: AppColors.primary),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Text(
                  parent.nickname,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: Colors.white),
                ),
              ),
              if (onEdit != null)
                FilledButton(
                  onPressed: onEdit,
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: AppColors.primary,
                    minimumSize: const Size(80, 44),
                    shape: const StadiumBorder(),
                    textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                  child: const Text('수정'),
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
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                  decoration: BoxDecoration(color: AppColors.mint, borderRadius: BorderRadius.circular(14)),
                  child: Text(tag, style: const TextStyle(fontSize: 16, color: AppColors.primary)),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _OutlinedRow extends StatelessWidget {
  const _OutlinedRow({required this.icon, required this.label, required this.onTap, this.bold = false});

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: AppColors.track),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          child: Row(
            children: [
              Icon(icon, color: AppColors.primary),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
                    color: AppColors.primary,
                  ),
                ),
              ),
              const Icon(Icons.chevron_right, color: AppColors.subtext),
            ],
          ),
        ),
      ),
    );
  }
}

class _ChevronRow extends StatelessWidget {
  const _ChevronRow({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        child: Row(
          children: [
            Expanded(child: Text(label, style: const TextStyle(fontSize: 16, color: AppColors.text))),
            const Icon(Icons.chevron_right, color: AppColors.subtext),
          ],
        ),
      ),
    );
  }
}

class _SwitchRow extends StatelessWidget {
  const _SwitchRow({required this.label, required this.value, required this.onChanged});

  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 4, 8, 4),
      child: Row(
        children: [
          Expanded(child: Text(label, style: const TextStyle(fontSize: 16, color: AppColors.text))),
          Switch(
            value: value,
            onChanged: onChanged,
            activeThumbColor: Colors.white,
            activeTrackColor: AppColors.primaryGlow,
            inactiveThumbColor: Colors.white,
            inactiveTrackColor: AppColors.track,
            trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
          ),
        ],
      ),
    );
  }
}

class _ConsentRow extends StatelessWidget {
  const _ConsentRow({required this.label, required this.agreedAt, required this.onRevoke, this.onAgree});

  final String label;

  /// 동의 안 함 → null
  final DateTime? agreedAt;
  final VoidCallback onRevoke;

  /// 동의 안 함일 때 다시 동의 (선택 동의만)
  final VoidCallback? onAgree;

  @override
  Widget build(BuildContext context) {
    final at = agreedAt;
    final agreed = at != null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 10, 8, 10),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: const TextStyle(fontSize: 16, color: AppColors.text)),
                Text(
                  agreed ? _MyInfoScreenState._date(at) : '동의 안 함',
                  style: const TextStyle(fontSize: 15, color: AppColors.subtext),
                ),
              ],
            ),
          ),
          if (agreed || onAgree != null)
            TextButton(
              onPressed: agreed ? onRevoke : onAgree,
              style: TextButton.styleFrom(foregroundColor: AppColors.text, minimumSize: const Size(56, 44)),
              child: Text(
                agreed ? '철회' : '동의',
                style: const TextStyle(fontSize: 16, decoration: TextDecoration.underline),
              ),
            ),
        ],
      ),
    );
  }
}

/// 기록 공간 삭제 상태 카드
/// 없음 → 삭제 요청 (관리자) / pending → 동의 현황 · 동의 · 취소 / scheduled → 삭제 예정일 · 취소
/// 관리자 아님 → 안내만
class _DeletionCard extends StatelessWidget {
  const _DeletionCard({
    required this.parent,
    required this.deletion,
    required this.onRequest,
    required this.onApprove,
    required this.onCancel,
  });

  final ParentInfo parent;
  final ParentDeletion? deletion;
  final VoidCallback onRequest;
  final VoidCallback onApprove;
  final VoidCallback onCancel;

  static String _md(DateTime d) => '${d.month}월 ${d.day}일';

  @override
  Widget build(BuildContext context) {
    final error = Theme.of(context).colorScheme.error;
    final d = deletion;
    final admin = parent.isAdmin;

    final (String title, String body) = switch (d?.status) {
      null => (
          '${parent.nickname} 기록 공간 삭제',
          '가족 모두가 남긴 기록과 음성 파일을 모두 지워요. 관리자가 여러 명이면 모두 동의해야 해요.',
        ),
      'pending' => (
          '삭제 동의를 기다리고 있어요',
          '관리자 ${d!.adminsTotal}명 중 ${d.adminsApproved}명 동의 · ${_md(d.approvalDeadline)}까지 모두 동의하지 않으면 요청이 사라져요.',
        ),
      'scheduled' => (
          '${_md(d!.scheduledFor!)}에 삭제돼요',
          '지금은 기록을 남기거나 고칠 수 없어요. 관리자는 그전까지 취소할 수 있어요.',
        ),
      _ => ('삭제를 진행하고 있어요', '잠시 뒤 이 기록 공간이 사라져요.'),
    };

    final buttons = <Widget>[
      if (admin && d == null) _DangerButton(label: '기록 공간 삭제', color: error, onPressed: onRequest),
      if (admin && d != null && d.isPending && !d.approvedByMe)
        _DangerButton(label: '삭제에 동의', color: error, onPressed: onApprove, filled: true),
      if (admin && d != null && (d.status == 'pending' || d.status == 'scheduled'))
        _DangerButton(
          label: d.isPending && !d.approvedByMe ? '거절 (요청 취소)' : '삭제 취소',
          color: AppColors.primary,
          onPressed: onCancel,
        ),
    ];

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: d == null ? AppColors.track : error.withValues(alpha: 0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text)),
          const SizedBox(height: 4),
          Text(body, style: const TextStyle(fontSize: 15, color: AppColors.subtext, height: 1.5)),
          for (final b in buttons) ...[const SizedBox(height: 12), b],
        ],
      ),
    );
  }
}

class _DangerButton extends StatelessWidget {
  const _DangerButton({required this.label, required this.color, required this.onPressed, this.filled = false});

  final String label;
  final Color color;
  final VoidCallback onPressed;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    const shape = StadiumBorder();
    const text = TextStyle(fontSize: 16, fontWeight: FontWeight.w700);
    if (filled) {
      return FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: color,
          minimumSize: const Size.fromHeight(48),
          shape: shape,
          textStyle: text,
        ),
        child: Text(label),
      );
    }
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        foregroundColor: color,
        side: BorderSide(color: color),
        minimumSize: const Size.fromHeight(48),
        shape: shape,
        textStyle: text,
      ),
      child: Text(label),
    );
  }
}

class _PillButton extends StatelessWidget {
  const _PillButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        backgroundColor: Colors.white,
        foregroundColor: AppColors.text,
        side: const BorderSide(color: AppColors.track),
        minimumSize: const Size.fromHeight(52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: Text(label),
    );
  }
}
