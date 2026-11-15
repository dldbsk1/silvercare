import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../home/home_api.dart';
import '../symptom_api.dart';

/// A-SYM-001/002 증상 기록 (기록함 → 증상 기록)
/// - 증상 칩 6개: 우리 가족 기록에서 많이 나온 조사표 항목 (기록 적으면 기본 6개) + 기타(직접 입력)
/// - 시간대 (필수) · 횟수 1~20 · 메모 (선택)
/// - 조사표 증상 고르면 최근 4주 막대 (저장 뒤 새로고침)
class SymptomScreen extends StatefulWidget {
  const SymptomScreen({super.key, required this.parentId, this.symptomApi});

  final String parentId;

  /// 테스트용 교체
  final SymptomApi? symptomApi;

  @override
  State<SymptomScreen> createState() => _SymptomScreenState();
}

class _SymptomScreenState extends State<SymptomScreen> {
  late final SymptomApi _api = widget.symptomApi ?? SymptomApi();
  final _custom = TextEditingController();
  final _note = TextEditingController();

  static const _maxCount = 20;

  List<SymptomOption>? _options;
  String? _loadError;

  String? _type;
  String? _timeBand;
  int _count = 1;
  bool _saving = false;

  /// 같은 저장 재시도 → 같은 키 (성공하면 새 키)
  String _idempotencyKey = HomeApi.newIdempotencyKey();

  SymptomWeekly? _weekly;

  @override
  void initState() {
    super.initState();
    _loadOptions();
  }

  @override
  void dispose() {
    _custom.dispose();
    _note.dispose();
    super.dispose();
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _loadOptions() async {
    setState(() => _loadError = null);
    try {
      final options = await _api.fetchSuggestions(widget.parentId);
      if (mounted) setState(() => _options = options);
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    }
  }

  bool get _isCustom => _type == customSymptom;

  String? get _customLabel => _isCustom ? _custom.text.trim() : null;

  bool get _canSave =>
      !_saving && _type != null && _timeBand != null && (!_isCustom || _custom.text.trim().isNotEmpty);

  void _select(String type) {
    setState(() {
      _type = type;
      _weekly = null;
    });
    if (type != customSymptom) _loadWeekly(type);
  }

  Future<void> _loadWeekly(String type, {String? customLabel}) async {
    try {
      final weekly = await _api.fetchWeekly(widget.parentId, type, customLabel: customLabel);
      // 그사이 다른 증상 고름 → 버림
      if (mounted && _type == type) setState(() => _weekly = weekly);
    } on ApiException {
      // 막대는 보조 정보 → 실패해도 저장 가능
    }
  }

  Future<void> _save() async {
    final type = _type!;
    final customLabel = _customLabel;
    setState(() => _saving = true);
    try {
      await _api.create(
        widget.parentId,
        SymptomInput(
          type: type,
          customLabel: customLabel,
          timeBand: _timeBand!,
          count: _count,
          note: _note.text.trim(),
        ),
        idempotencyKey: _idempotencyKey,
      );
      if (!mounted) return;
      _idempotencyKey = HomeApi.newIdempotencyKey();
      recordsChanged.value++;
      _note.clear();
      setState(() => _count = 1);
      _toast('증상을 기록했어요.');
      await _loadWeekly(type, customLabel: customLabel);
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        titleSpacing: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: '뒤로',
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: const Text(
          '증상 기록',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.text),
        ),
      ),
      body: _options == null
          ? Center(
              child: _loadError == null
                  ? const CircularProgressIndicator()
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_loadError!, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
                        TextButton(onPressed: _loadOptions, child: const Text('다시 시도')),
                      ],
                    ),
            )
          : _form(),
    );
  }

  Widget _form() {
    final weekly = _weekly;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        const _Question('어떤 모습이었나요?'),
        _symptomGrid(),
        const SizedBox(height: 24),
        const _Question('언제였나요?'),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final e in timeBandLabels.entries)
              _Chip(
                label: e.value,
                selected: _timeBand == e.key,
                compact: true,
                onTap: () => setState(() => _timeBand = e.key),
              ),
          ],
        ),
        const SizedBox(height: 24),
        const _Question('횟수'),
        _counter(),
        const SizedBox(height: 24),
        const _Question('메모 (선택)'),
        TextField(
          controller: _note,
          minLines: 3,
          maxLines: 5,
          maxLength: 500,
          style: const TextStyle(fontSize: 16, color: AppColors.text),
          decoration: _boxDecoration('예: 새벽 3시에 현관문을 열려고 하심').copyWith(counterText: ''),
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _canSave ? _save : null,
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.primaryGlow,
            disabledBackgroundColor: AppColors.track,
            disabledForegroundColor: AppColors.subtext,
            minimumSize: const Size.fromHeight(52),
            shape: const StadiumBorder(),
            textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
          child: _saving
              ? const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                )
              : const Text('저장'),
        ),
        if (weekly != null) ...[
          const SizedBox(height: 24),
          _WeeklyCard(weekly: weekly),
        ],
      ],
    );
  }

  /// 3칸 격자. 기타(직접 입력) → 고르면 입력칸으로 바뀜
  Widget _symptomGrid() {
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 6.0;
        final cell = (constraints.maxWidth - gap * 2) / 3;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final option in _options!)
              SizedBox(
                width: cell,
                child: _Chip(
                  label: option.label,
                  selected: _type == option.type,
                  onTap: () => _select(option.type),
                ),
              ),
            if (_isCustom)
              SizedBox(
                width: constraints.maxWidth,
                child: TextField(
                  controller: _custom,
                  autofocus: true,
                  maxLength: 20,
                  onChanged: (_) => setState(() {}),
                  style: const TextStyle(fontSize: 16, color: AppColors.text),
                  decoration: _boxDecoration('증상을 직접 적어 주세요', radius: 22, focused: true)
                      .copyWith(counterText: ''),
                ),
              )
            else
              SizedBox(
                width: cell * 2 + gap,
                child: _Chip(label: '기타(직접 입력)', selected: false, onTap: () => _select(customSymptom)),
              ),
          ],
        );
      },
    );
  }

  Widget _counter() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _RoundIconButton(
          icon: Icons.remove,
          tooltip: '한 번 줄이기',
          // 범위는 누를 때 다시 확인 (화면 갱신 전 연타 → 1 아래 X)
          onPressed: _count > 1 ? () => setState(() => _count = (_count - 1).clamp(1, _maxCount)) : null,
        ),
        SizedBox(
          width: 120,
          child: Text(
            '$_count번',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: AppColors.text),
          ),
        ),
        _RoundIconButton(
          icon: Icons.add,
          tooltip: '한 번 늘리기',
          onPressed: _count < _maxCount ? () => setState(() => _count = (_count + 1).clamp(1, _maxCount)) : null,
        ),
      ],
    );
  }

  InputDecoration _boxDecoration(String hint, {double radius = 16, bool focused = false}) {
    OutlineInputBorder border(Color color, [double width = 1]) => OutlineInputBorder(
          borderRadius: BorderRadius.circular(radius),
          borderSide: BorderSide(color: color, width: width),
        );
    return InputDecoration(
      hintText: hint,
      hintStyle: const TextStyle(fontSize: 16, color: AppColors.subtext),
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      enabledBorder: border(focused ? AppColors.primaryGlow : AppColors.track, focused ? 1.5 : 1),
      focusedBorder: border(AppColors.primaryGlow, 1.5),
    );
  }
}

class _Question extends StatelessWidget {
  const _Question(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Text(text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text)),
      );
}

/// Figma 칩: 흰 바탕 + 회색 테두리 / 고름 → mint 바탕 + 진녹색 테두리
class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onTap, this.compact = false});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  /// 시간대 칩 (작게)
  final bool compact;

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
            height: compact ? 44 : 46,
            constraints: compact ? const BoxConstraints(minWidth: 56) : null,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            alignment: Alignment.center,
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 16,
                fontWeight: compact ? FontWeight.w400 : FontWeight.w500,
                color: selected ? AppColors.primary : AppColors.text,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _RoundIconButton extends StatelessWidget {
  const _RoundIconButton({required this.icon, required this.tooltip, required this.onPressed});

  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final color = onPressed == null ? AppColors.track : AppColors.primary;
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      iconSize: 28,
      style: IconButton.styleFrom(
        fixedSize: const Size(48, 48),
        side: BorderSide(color: color, width: 1.5),
        foregroundColor: color,
      ),
      icon: Icon(icon),
    );
  }
}

/// 최근 4주 막대 (Figma: 3주 전 · 2주 전 · 지난 주 · 이번 주, 이번 주 진하게)
class _WeeklyCard extends StatelessWidget {
  const _WeeklyCard({required this.weekly});

  final SymptomWeekly weekly;

  static const _weekLabels = ['3주 전', '2주 전', '지난 주', '이번 주'];
  static const _maxBar = 64.0;

  @override
  Widget build(BuildContext context) {
    final counts = weekly.counts;
    final max = counts.fold<int>(0, (a, b) => a > b ? a : b);
    return Semantics(
      label: '최근 4주 ${weekly.label}: '
          '${[for (var i = 0; i < counts.length; i++) '${_weekLabels[i]} ${counts[i]}번'].join(', ')}',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 16, 16, 20),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
        child: Column(
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '최근 4주',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.mint,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: AppColors.primaryGlow),
                  ),
                  child: Text(weekly.label, style: const TextStyle(fontSize: 15, color: AppColors.primary)),
                ),
              ],
            ),
            const SizedBox(height: 16),
            SizedBox(
              height: _maxBar + 56,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  for (var i = 0; i < counts.length; i++)
                    Expanded(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          Text('${counts[i]}번', style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                          const SizedBox(height: 4),
                          Container(
                            width: 32,
                            height: counts[i] == 0 ? 3 : (_maxBar * counts[i] / max).clamp(14.0, _maxBar),
                            decoration: BoxDecoration(
                              color: counts[i] == 0
                                  ? AppColors.track
                                  : (i == counts.length - 1 ? AppColors.primary : AppColors.primaryGlow),
                              borderRadius: BorderRadius.circular(6),
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(_weekLabels[i], style: const TextStyle(fontSize: 15, color: AppColors.subtext)),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
