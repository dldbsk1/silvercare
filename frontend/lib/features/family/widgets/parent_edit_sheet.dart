import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../family_api.dart';
import 'family_widgets.dart';

/// 부모님 정보 수정 시트 (관리자. 가족 탭 부모님 카드 · 내 정보 "수정")
/// 저장 → ParentEdit / 닫기 → null
class ParentEditSheet extends StatefulWidget {
  const ParentEditSheet({super.key, required this.parent});

  final ParentInfo parent;

  @override
  State<ParentEditSheet> createState() => _ParentEditSheetState();
}

class _ParentEditSheetState extends State<ParentEditSheet> {
  late final _nickname = TextEditingController(text: widget.parent.nickname);
  late String? _ageBand = widget.parent.ageBand;
  late String _stage = widget.parent.applyStage;
  late bool _cohabiting = widget.parent.cohabiting;
  late DateTime? _surveyDate = widget.parent.surveyDate;

  @override
  void dispose() {
    _nickname.dispose();
    super.dispose();
  }

  bool get _valid => _nickname.text.trim().isNotEmpty;

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _surveyDate ?? now,
      firstDate: DateTime(now.year - 1),
      lastDate: DateTime(now.year + 2),
      helpText: '방문조사일',
    );
    if (picked != null) setState(() => _surveyDate = picked);
  }

  @override
  Widget build(BuildContext context) {
    final date = _surveyDate;
    return Padding(
      // 키보드 위로
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SheetFrame(
        title: '부모님 정보',
        children: [
          const SizedBox(height: 20),
          const _Label('호칭'),
          TextField(
            controller: _nickname,
            maxLength: 20,
            onChanged: (_) => setState(() {}),
            style: const TextStyle(fontSize: 16, color: AppColors.text),
            decoration: const InputDecoration(hintText: '예: 엄마', counterText: ''),
          ),
          const SizedBox(height: 16),
          const _Label('나이대 (선택)'),
          _Chips(
            options: ageBandLabels,
            selected: _ageBand,
            // 다시 누르면 해제
            onSelect: (v) => setState(() => _ageBand = _ageBand == v ? null : v),
          ),
          const SizedBox(height: 16),
          const _Label('신청 단계'),
          _Chips(options: applyStageLabels, selected: _stage, onSelect: (v) => setState(() => _stage = v)),
          const SizedBox(height: 16),
          const _Label('함께 사는지'),
          _Chips(
            options: const {'yes': '함께 살아요', 'no': '따로 살아요'},
            selected: _cohabiting ? 'yes' : 'no',
            onSelect: (v) => setState(() => _cohabiting = v == 'yes'),
          ),
          const SizedBox(height: 16),
          const _Label('방문조사일'),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _pickDate,
                  icon: const Icon(Icons.event_outlined),
                  label: Text(date == null ? '정하기' : '${date.year}년 ${date.month}월 ${date.day}일'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.text,
                    side: const BorderSide(color: AppColors.track),
                    minimumSize: const Size.fromHeight(48),
                    alignment: Alignment.centerLeft,
                    textStyle: const TextStyle(fontSize: 16),
                  ),
                ),
              ),
              if (date != null)
                IconButton(
                  tooltip: '조사일 지우기',
                  onPressed: () => setState(() => _surveyDate = null),
                  icon: const Icon(Icons.close, color: AppColors.subtext),
                ),
            ],
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _valid
                ? () => Navigator.of(context).pop(ParentEdit(
                      nickname: _nickname.text.trim(),
                      ageBand: _ageBand,
                      applyStage: _stage,
                      cohabiting: _cohabiting,
                      surveyDate: _surveyDate,
                    ))
                : null,
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primaryGlow,
              disabledBackgroundColor: AppColors.track,
              minimumSize: const Size.fromHeight(52),
              shape: const StadiumBorder(),
              textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            child: const Text('저장'),
          ),
        ],
      ),
    );
  }
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.text)),
      );
}

class _Chips extends StatelessWidget {
  const _Chips({required this.options, required this.selected, required this.onSelect});

  final Map<String, String> options;
  final String? selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final e in options.entries)
          ChoiceChip(
            label: Text(e.value),
            selected: e.key == selected,
            onSelected: (_) => onSelect(e.key),
            showCheckmark: false,
            selectedColor: AppColors.mint,
            backgroundColor: Colors.white,
            side: BorderSide(color: e.key == selected ? AppColors.primaryGlow : AppColors.track),
            shape: const StadiumBorder(),
            labelStyle: TextStyle(fontSize: 16, color: e.key == selected ? AppColors.primary : AppColors.text),
          ),
      ],
    );
  }
}
