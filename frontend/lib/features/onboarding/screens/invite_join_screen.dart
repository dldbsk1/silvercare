import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../family/invite_api.dart';
import '../setup_api.dart';

/// 초대 수락 (A-FAM-001, 초대받은 사람)
///
/// 1. 초대 코드 붙여넣기 (초대 메시지 통째·링크도 됨) → [확인] → POST /invites/preview
/// 2. 누가 · 어느 부모님 · 권한 확인 + 내 이름 (미설정만) + 가족 공유 동의
///    → [함께 기록하기] → PATCH /auth/me (이름) → POST /invites/accept → /auth/me 다음 단계
/// - 동의 문서 바뀜 (CONSENT_REQUIRED) → 미리보기 다시 + 다시 동의
/// - 초대 문제 (없음·사용됨·취소·만료) → 1단계로, 서버 문구 표시
class InviteJoinScreen extends StatefulWidget {
  const InviteJoinScreen({super.key, this.inviteApi, this.setupApi, this.authApi, this.initialText});

  /// 테스트용 교체
  final InviteApi? inviteApi;
  final SetupApi? setupApi;
  final AuthApi? authApi;

  /// 미리 채울 코드·링크 (딥링크 연결 시)
  final String? initialText;

  @override
  State<InviteJoinScreen> createState() => _InviteJoinScreenState();
}

class _InviteJoinScreenState extends State<InviteJoinScreen> {
  static const _roleText = {'writer': '기록하고 볼 수 있어요', 'viewer': '기록을 볼 수만 있어요'};

  late final InviteApi _inviteApi = widget.inviteApi ?? InviteApi();
  late final SetupApi _setupApi = widget.setupApi ?? SetupApi();
  late final AuthApi _authApi = widget.authApi ?? AuthApi();

  final _linkController = TextEditingController();
  final _nameController = TextEditingController();

  /// 서버에 저장된 내 이름. null → 이름 칸 표시
  String? _savedName;
  bool _nameLoaded = false;

  String? _token;
  InvitePreview? _preview;
  bool _agreed = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _linkController.text = widget.initialText ?? '';
    _linkController.addListener(() => setState(() {}));
    _nameController.addListener(() => setState(() {}));
    _loadName();
  }

  @override
  void dispose() {
    _linkController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  /// 이름 정했는지 확인. 실패 → 이름 칸 보여 줌 (빈 칸)
  Future<void> _loadName() async {
    try {
      final me = await _authApi.fetchMe();
      _savedName = me.displayName;
    } on ApiException {
      _savedName = null;
    }
    if (mounted) setState(() => _nameLoaded = true);
  }

  String get _name => _nameController.text.trim();

  bool get _needsName => _nameLoaded && _savedName == null;

  String? get _parsedToken => parseInviteToken(_linkController.text);

  bool get _canAccept =>
      _agreed && !_busy && (!_needsName || (_name.isNotEmpty && _name.length <= 20));

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = data?.text?.trim() ?? '';
    if (text.isEmpty) {
      setState(() => _error = '복사한 내용이 없어요. 받은 초대 메시지를 복사해 주세요.');
      return;
    }
    _linkController.text = text;
    setState(() => _error = null);
  }

  Future<void> _check() async {
    final token = _parsedToken;
    if (token == null) {
      setState(() => _error = '초대 코드를 찾지 못했어요. 받은 메시지를 그대로 붙여넣어 주세요.');
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final preview = await _inviteApi.preview(token);
      if (!mounted) return;
      setState(() {
        _token = token;
        _preview = preview;
        _agreed = false;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _accept() async {
    final token = _token!;
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_needsName) {
        await _setupApi.updateName(_name);
        _savedName = _name;
      }
      await _inviteApi.accept(token, _preview!.shareDocument.version);
      await _goNext();
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.code == 'CONSENT_REQUIRED') {
        await _reloadDocument(token, e.message);
      } else if (e.code.startsWith('INVITE_')) {
        setState(() {
          _preview = null;
          _token = null;
          _error = e.message;
        });
      } else {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 동의 문서 바뀜 → 새 문서로 다시 동의
  Future<void> _reloadDocument(String token, String message) async {
    try {
      final preview = await _inviteApi.preview(token);
      if (!mounted) return;
      setState(() {
        _preview = preview;
        _agreed = false;
        _error = message;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _goNext() async {
    final me = await _authApi.fetchMe();
    if (mounted) context.go(me.nextRoute);
  }

  void _back() {
    if (_preview != null && !_busy) {
      setState(() {
        _preview = null;
        _token = null;
        _error = null;
      });
    } else if (context.canPop()) {
      context.pop();
    } else {
      context.go('/onboarding/setup');
    }
  }

  @override
  Widget build(BuildContext context) {
    final preview = _preview;
    return PopScope(
      canPop: preview == null,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: AppColors.background,
          surfaceTintColor: Colors.transparent,
          leading: IconButton(icon: const Icon(Icons.arrow_back), tooltip: '뒤로', onPressed: _back),
        ),
        body: SafeArea(
          top: false,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(24, 4, 24, 24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (preview == null) ..._inputStep() else ..._confirmStep(preview),
                      if (_error != null) ...[
                        const SizedBox(height: 16),
                        Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                      ],
                    ],
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                child: _bottomButton(preview),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ── 1단계: 붙여넣기 ──

  List<Widget> _inputStep() => [
        const _Title('받은 초대 코드를\n붙여넣어 주세요'),
        const SizedBox(height: 8),
        const Text(
          '카카오톡·문자로 받은 초대 메시지를 통째로 붙여넣어도 돼요.',
          style: TextStyle(fontSize: 15, height: 1.5, color: AppColors.subtext),
        ),
        const SizedBox(height: 24),
        TextField(
          controller: _linkController,
          minLines: 2,
          maxLines: 4,
          textCapitalization: TextCapitalization.characters,
          style: const TextStyle(fontSize: 15, color: AppColors.text),
          decoration: _inputDecoration('초대 코드 (예: K7QM-4XPA)'),
        ),
        const SizedBox(height: 10),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _paste,
            icon: const Icon(Icons.content_paste, size: 18),
            label: const Text('붙여넣기'),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.primary,
              side: const BorderSide(color: AppColors.track),
              backgroundColor: Colors.white,
              shape: const StadiumBorder(),
              minimumSize: const Size(0, 44),
            ),
          ),
        ),
      ];

  // ── 2단계: 확인 + 동의 ──

  List<Widget> _confirmStep(InvitePreview preview) {
    final inviter = preview.inviterName ?? '가족';
    final until = preview.expiresAt;
    return [
      _Title('$inviter님이\n${preview.parentNickname} 기록에 초대했어요'),
      const SizedBox(height: 20),
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _InfoRow(label: '부모님', value: preview.parentNickname),
            _InfoRow(label: '초대한 사람', value: inviter),
            _InfoRow(label: '권한', value: _roleText[preview.role] ?? preview.role),
            _InfoRow(label: '초대 기간', value: '${until.month}월 ${until.day}일까지'),
          ],
        ),
      ),
      if (preview.alreadyMember) ...[
        const SizedBox(height: 20),
        const Text(
          '이미 함께 기록하고 있어요.',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: AppColors.primary),
        ),
      ] else ...[
        if (_needsName) ...[
          const _Label('내 이름', help: '가족에게 이렇게 보여요'),
          TextField(
            controller: _nameController,
            maxLength: 20,
            style: const TextStyle(fontSize: 16, color: AppColors.text),
            decoration: _inputDecoration('예: 홍길동').copyWith(counterText: ''),
          ),
        ],
        _Label(preview.shareDocument.title),
        Container(
          constraints: const BoxConstraints(maxHeight: 180),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.track),
          ),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(14),
            child: Text(
              preview.shareDocument.content,
              style: const TextStyle(fontSize: 14, height: 1.6, color: AppColors.text),
            ),
          ),
        ),
        const SizedBox(height: 8),
        CheckboxListTile(
          value: _agreed,
          onChanged: _busy ? null : (value) => setState(() => _agreed = value ?? false),
          title: const Text('위 내용을 읽고 동의해요', style: TextStyle(fontSize: 16, color: AppColors.text)),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          activeColor: AppColors.primaryGlow,
        ),
      ],
    ];
  }

  Widget _bottomButton(InvitePreview? preview) {
    final String label;
    final VoidCallback? onPressed;
    if (preview == null) {
      label = '확인';
      onPressed = !_busy && _linkController.text.trim().isNotEmpty ? _check : null;
    } else if (preview.alreadyMember) {
      label = '홈으로';
      onPressed = _busy ? null : _goNext;
    } else {
      label = '함께 기록하기';
      onPressed = _canAccept ? _accept : null;
    }
    return FilledButton(
      onPressed: onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.primaryGlow,
        disabledBackgroundColor: AppColors.track,
        disabledForegroundColor: AppColors.subtext,
        minimumSize: const Size.fromHeight(52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: _busy
          ? const SizedBox.square(dimension: 22, child: CircularProgressIndicator(strokeWidth: 2))
          : Text(label),
    );
  }

  InputDecoration _inputDecoration(String hint) => InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: AppColors.subtext),
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.track),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.primaryGlow),
        ),
      );
}

class _Title extends StatelessWidget {
  const _Title(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Text(
        text,
        style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, height: 1.5, color: AppColors.text),
      );
}

/// 항목 제목 (첫 설정 화면과 같은 모양)
class _Label extends StatelessWidget {
  const _Label(this.text, {this.help});

  final String text;
  final String? help;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 24, bottom: 10),
        child: Wrap(
          crossAxisAlignment: WrapCrossAlignment.end,
          spacing: 8,
          children: [
            Text(text, style: const TextStyle(fontSize: 18, color: AppColors.subtext)),
            if (help != null) Text(help!, style: const TextStyle(fontSize: 14, color: AppColors.subtext)),
          ],
        ),
      );
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 88,
              child: Text(label, style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
            ),
            Expanded(
              child: Text(value, style: const TextStyle(fontSize: 15, color: AppColors.text)),
            ),
          ],
        ),
      );
}
