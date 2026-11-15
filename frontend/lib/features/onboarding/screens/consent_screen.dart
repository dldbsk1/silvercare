import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../../shared/widgets/step_progress.dart';
import '../consent_api.dart';

/// 민감정보 동의 (A-ON-002, 온보딩 2단계)
///
/// 흐름: GET /v1/consents/required → 체크 → POST /v1/consents → GET /v1/auth/me → 다음 단계
/// - 필수 (서비스·개인정보·건강정보) 모두 체크해야 다음
/// - 선택 (알림) 체크 안 하면 agreed=false로 보냄
/// - 문서 버전은 받은 그대로 (문구 바뀌면 서버 400 → 다시 불러오기)
/// - [보기] → 서버 문구 전체 (아래에서 올라오는 창)
class ConsentScreen extends StatefulWidget {
  const ConsentScreen({super.key, this.consentApi, this.authApi});

  /// 테스트용 교체
  final ConsentApi? consentApi;
  final AuthApi? authApi;

  @override
  State<ConsentScreen> createState() => _ConsentScreenState();
}

class _ConsentScreenState extends State<ConsentScreen> {
  /// 화면 문구 (Figma). 서버 제목과 다르면 이 문구 사용, 없는 종류는 서버 제목
  static const _labels = {
    'service': '서비스 이용 동의',
    'privacy': '개인정보 수집·이용 동의',
    'health': '건강정보 수집·이용 동의',
    'noti': '알림 수신 동의',
  };

  /// 표시 순서
  static const _order = ['service', 'privacy', 'health', 'noti'];

  late final ConsentApi _consentApi = widget.consentApi ?? ConsentApi();
  late final AuthApi _authApi = widget.authApi ?? AuthApi();

  List<ConsentDocument>? _documents;
  final Set<String> _checked = {};
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _documents = null;
      _error = null;
    });
    try {
      final documents = await _consentApi.fetchRequired();
      documents.sort((a, b) => _rank(a.type).compareTo(_rank(b.type)));
      if (!mounted) return;
      setState(() {
        _documents = documents;
        _checked.removeWhere((type) => documents.every((d) => d.type != type));
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  int _rank(String type) {
    final index = _order.indexOf(type);
    return index == -1 ? _order.length : index;
  }

  bool get _allChecked => _documents != null && _documents!.every((d) => _checked.contains(d.type));

  bool get _requiredChecked =>
      _documents != null && _documents!.where((d) => d.required).every((d) => _checked.contains(d.type));

  void _toggleAll() {
    setState(() {
      if (_allChecked) {
        _checked.clear();
      } else {
        _checked.addAll(_documents!.map((d) => d.type));
      }
    });
  }

  void _toggle(String type) {
    setState(() => _checked.contains(type) ? _checked.remove(type) : _checked.add(type));
  }

  Future<void> _submit() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await _consentApi.save(_documents!, _checked);
      final me = await _authApi.fetchMe();
      if (mounted) context.go(me.nextRoute);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
      // 문구 버전 바뀜 → 새 문서로 다시
      if (e.code == 'INVALID_REQUEST') _load();
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _showDocument(ConsentDocument doc) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: AppColors.background,
      builder: (context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.92,
        builder: (context, controller) => ListView(
          controller: controller,
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 32),
          children: [
            Text(
              _labels[doc.type] ?? doc.title,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            const SizedBox(height: 4),
            Text('버전 ${doc.docVersion}', style: const TextStyle(fontSize: 14, color: AppColors.subtext)),
            const SizedBox(height: 16),
            Text(doc.content, style: const TextStyle(fontSize: 16, height: 1.6, color: AppColors.text)),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: '뒤로',
          onPressed: () => context.canPop() ? context.pop() : context.go('/login'),
        ),
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
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const StepProgress(current: 2),
                    const SizedBox(height: 24),
                    const Text(
                      '부모님 건강 정보는\n기록 정리에만 씁니다',
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        height: 1.5,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 22),
                    _body(),
                    if (_error != null && _documents != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: FilledButton(
                onPressed: _requiredChecked && !_saving ? _submit : null,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.primaryGlow,
                  disabledBackgroundColor: AppColors.track,
                  disabledForegroundColor: AppColors.subtext,
                  minimumSize: const Size.fromHeight(52),
                  shape: const StadiumBorder(),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                child: _saving
                    ? const SizedBox.square(dimension: 22, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('다음'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    final documents = _documents;
    if (documents == null && _error != null) {
      return Column(
        children: [
          Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.subtext)),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: _load, child: const Text('다시 불러오기')),
        ],
      );
    }
    if (documents == null) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 48),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    // Figma: 카드 테두리·행 사이 2px = mint (행 사이 구분선처럼 보임)
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppColors.mint,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.mint),
      ),
      child: Column(
        children: [
          _ConsentRow(
            checked: _allChecked,
            onTap: _toggleAll,
            background: AppColors.track,
            title: const Text(
              '전체 동의',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.primary),
            ),
          ),
          for (final doc in documents) ...[
            const SizedBox(height: 2),
            _ConsentRow(
              checked: _checked.contains(doc.type),
              onTap: () => _toggle(doc.type),
              title: Text.rich(
                TextSpan(children: [
                  TextSpan(
                    text: doc.required ? '[필수] ' : '[선택] ',
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.primary),
                  ),
                  TextSpan(
                    text: _labels[doc.type] ?? doc.title,
                    style: const TextStyle(fontSize: 15, color: AppColors.text),
                  ),
                ]),
              ),
              trailing: TextButton(
                onPressed: () => _showDocument(doc),
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.subtext,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  textStyle: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    decoration: TextDecoration.underline,
                  ),
                ),
                child: const Text('보기'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// 동의 한 줄 (Figma: 높이 52, 체크 24 모서리 6, 왼쪽 15)
class _ConsentRow extends StatelessWidget {
  const _ConsentRow({
    required this.checked,
    required this.onTap,
    required this.title,
    this.trailing,
    this.background = Colors.white,
  });

  final bool checked;
  final VoidCallback onTap;
  final Widget title;
  final Widget? trailing;
  final Color background;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: background,
      child: InkWell(
        onTap: onTap,
        child: Semantics(
          checked: checked,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 52),
            child: Padding(
              padding: EdgeInsets.only(left: 15, right: trailing == null ? 15 : 4),
              child: Row(
                children: [
                  _CheckBox(checked: checked),
                  const SizedBox(width: 11),
                  Expanded(child: title),
                  ?trailing,
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CheckBox extends StatelessWidget {
  const _CheckBox({required this.checked});

  final bool checked;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 24,
      height: 24,
      decoration: BoxDecoration(
        color: checked ? AppColors.primaryGlow : Colors.white,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.primaryGlow),
      ),
      child: checked ? const Icon(Icons.check, size: 18, color: Colors.white) : null,
    );
  }
}
