import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../../shared/widgets/step_progress.dart';
import '../setup_api.dart';

/// 첫 설정: 내 이름 + 부모님 등록 (A-ON-003, 온보딩 마지막 단계)
///
/// Figma "누구의 기록을 남길까요?" + 위에 내 이름 칸 (별도 이름 화면 대신)
/// 흐름: [시작하기] → PATCH /v1/auth/me (이름) → POST /v1/parents → GET /v1/auth/me → 홈
/// - 이름: 이미 정했으면 미리 채움, 바뀐 경우만 저장
/// - 필수: 이름 · 호칭 · 신청 단계 · 함께 사는지 / 선택: 나이대 (다시 누르면 해제)
/// - 부모님 등록 재시도 → 같은 Idempotency-Key (두 번 생기지 않게)
class InitSetupScreen extends StatefulWidget {
  const InitSetupScreen({super.key, this.setupApi, this.authApi});

  /// 테스트용 교체
  final SetupApi? setupApi;
  final AuthApi? authApi;

  @override
  State<InitSetupScreen> createState() => _InitSetupScreenState();
}

class _InitSetupScreenState extends State<InitSetupScreen> {
  static const _custom = '직접입력';
  static const _nicknames = ['엄마', '아버지', _custom];
  static const _ageBands = {'60s': '60대', '70s': '70대', '80s': '80대', '90s+': '90대 이상'};
  static const _applyStages = {
    'before': '신청 전',
    'waiting': '조사 대기',
    'result': '결과 나옴',
    'renewal': '갱신 준비',
  };
  static const _cohabiting = {false: '따로 살아요', true: '같이 살아요'};

  late final SetupApi _setupApi = widget.setupApi ?? SetupApi();
  late final AuthApi _authApi = widget.authApi ?? AuthApi();
  final _idempotencyKey = SetupApi.newIdempotencyKey();

  final _nameController = TextEditingController();
  final _customNicknameController = TextEditingController();

  /// 서버에 저장된 내 이름 (같으면 다시 저장 X)
  String? _savedName;
  String? _nicknameChoice;
  String? _ageBand;
  String? _applyStage;
  bool? _livesTogether;

  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _nameController.addListener(() => setState(() {}));
    _customNicknameController.addListener(() => setState(() {}));
    _loadName();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _customNicknameController.dispose();
    super.dispose();
  }

  /// 이미 정한 이름 미리 채우기. 실패해도 입력은 가능
  Future<void> _loadName() async {
    try {
      final me = await _authApi.fetchMe();
      if (!mounted || me.displayName == null) return;
      _savedName = me.displayName;
      if (_nameController.text.isEmpty) _nameController.text = me.displayName!;
    } on ApiException {
      // 이름 칸 비워 둠
    }
  }

  String get _name => _nameController.text.trim();

  String get _nickname =>
      _nicknameChoice == _custom ? _customNicknameController.text.trim() : (_nicknameChoice ?? '');

  bool get _valid =>
      _name.isNotEmpty &&
      _name.length <= 20 &&
      _nickname.isNotEmpty &&
      _nickname.length <= 20 &&
      _applyStage != null &&
      _livesTogether != null;

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      if (_name != _savedName) {
        await _setupApi.updateName(_name);
        _savedName = _name;
      }
      await _setupApi.createParent(
        ParentInput(
          nickname: _nickname,
          ageBand: _ageBand,
          applyStage: _applyStage!,
          cohabiting: _livesTogether!,
        ),
        idempotencyKey: _idempotencyKey,
      );
      final me = await _authApi.fetchMe();
      if (mounted) context.go(me.nextRoute);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
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
          onPressed: () => context.canPop() ? context.pop() : context.go('/onboarding/consents'),
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
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const StepProgress(current: 4),
                    const SizedBox(height: 24),
                    const Text(
                      '누구의 기록을\n남길까요?',
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        height: 1.5,
                        color: AppColors.text,
                      ),
                    ),
                    const _SectionLabel('내 이름', help: '가족에게 이렇게 보여요'),
                    _TextInput(controller: _nameController, hint: '예: 홍길동'),
                    const _SectionLabel('호칭'),
                    _ChipGroup<String>(
                      options: {for (final n in _nicknames) n: n},
                      selected: _nicknameChoice,
                      onSelected: (value) => setState(() => _nicknameChoice = value),
                    ),
                    if (_nicknameChoice == _custom) ...[
                      const SizedBox(height: 10),
                      _TextInput(controller: _customNicknameController, hint: '예: 외할머니'),
                    ],
                    const _SectionLabel('나이대'),
                    _ChipGroup<String>(
                      options: _ageBands,
                      selected: _ageBand,
                      // 선택 항목 → 다시 누르면 해제
                      onSelected: (value) => setState(() => _ageBand = _ageBand == value ? null : value),
                    ),
                    const _SectionLabel('신청 단계'),
                    _ChipGroup<String>(
                      options: _applyStages,
                      selected: _applyStage,
                      onSelected: (value) => setState(() => _applyStage = value),
                    ),
                    const _SectionLabel('함께 사는지'),
                    _ChipGroup<bool>(
                      options: _cohabiting,
                      selected: _livesTogether,
                      onSelected: (value) => setState(() => _livesTogether = value),
                    ),
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
              child: FilledButton(
                onPressed: _valid && !_saving ? _submit : null,
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
                    : const Text('시작하기'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 항목 제목 (Figma: 18, 회색) + 도움말
class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text, {this.help});

  final String text;
  final String? help;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(text, style: const TextStyle(fontSize: 18, color: AppColors.subtext)),
          if (help != null) ...[
            const SizedBox(width: 8),
            Text(help!, style: const TextStyle(fontSize: 14, color: AppColors.subtext)),
          ],
        ],
      ),
    );
  }
}

/// 한 줄 입력 (20자, 흰 배경, 모서리 12)
class _TextInput extends StatelessWidget {
  const _TextInput({required this.controller, required this.hint});

  final TextEditingController controller;
  final String hint;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      maxLength: 20,
      style: const TextStyle(fontSize: 16, color: AppColors.text),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: AppColors.subtext),
        counterText: '',
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
      ),
    );
  }
}

/// 하나만 고르는 칩 (Figma: 높이 44, 모서리 22, 간격 10)
/// 선택: mint 배경 + 녹색 테두리 / 기본: 흰 배경 + 회색 테두리
class _ChipGroup<T> extends StatelessWidget {
  const _ChipGroup({required this.options, required this.selected, required this.onSelected});

  /// 값 → 화면 글자 (순서 유지)
  final Map<T, String> options;
  final T? selected;
  final ValueChanged<T> onSelected;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final entry in options.entries)
          _Chip(
            label: entry.value,
            selected: entry.key == selected,
            onTap: () => onSelected(entry.key),
          ),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onTap});

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
        shape: StadiumBorder(
          side: BorderSide(color: selected ? AppColors.primaryGlow : AppColors.track),
        ),
        child: InkWell(
          onTap: onTap,
          customBorder: const StadiumBorder(),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Text(
                label,
                style: TextStyle(
                  fontSize: 16,
                  color: selected ? AppColors.primary : AppColors.text,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
