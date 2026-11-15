import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../family/widgets/family_widgets.dart';
import '../../home/home_api.dart';
import '../record_api.dart';
import '../symptom_api.dart';

/// 기록 상세 시트·확인 창 (분류 바꾸기 · 출처 · 증상 고치기 · 기록지에서 제외)

/// 한 기록에 붙일 수 있는 분류 수 (서버 item_codes 최대)
const maxItemCodes = 10;

ButtonStyle sheetButtonStyle() => FilledButton.styleFrom(
      backgroundColor: AppColors.primaryGlow,
      disabledBackgroundColor: AppColors.track,
      disabledForegroundColor: AppColors.subtext,
      minimumSize: const Size.fromHeight(52),
      shape: const StadiumBorder(),
      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
    );

/// Figma 칩: 흰 바탕 + 회색 테두리 / 고름 → mint 바탕 + 진녹색 테두리
class SelectChip extends StatelessWidget {
  const SelectChip({super.key, required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? AppColors.mint : Colors.white,
      shape: StadiumBorder(side: BorderSide(color: selected ? AppColors.primaryGlow : AppColors.track)),
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
                fontWeight: selected ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 10),
        child: Text(text, style: const TextStyle(fontSize: 16, color: AppColors.subtext)),
      );
}

// ── 분류 바꾸기 ──

/// 영역 칩 + 항목 여러 개 고르기 (최대 10). 미분류 → 모두 비움
/// 결과: 고른 코드 (빈 목록 = 미분류) / 닫음 → null
Future<List<String>?> showClassifySheet(
  BuildContext context, {
  required List<SurveyItem> items,
  required List<String> selected,
}) =>
    showFamilySheet<List<String>>(context, (_) => ClassifySheet(items: items, selected: selected));

class ClassifySheet extends StatefulWidget {
  const ClassifySheet({super.key, required this.items, required this.selected});

  final List<SurveyItem> items;
  final List<String> selected;

  @override
  State<ClassifySheet> createState() => _ClassifySheetState();
}

class _ClassifySheetState extends State<ClassifySheet> {
  static const _areas = ['physical', 'cognitive', 'behavior', 'nursing', 'rehab', 'uncat'];

  /// 고른 순서 유지
  late final List<String> _codes = [...widget.selected];
  late String _area = _initialArea();

  String _initialArea() {
    if (widget.selected.isEmpty) return 'physical';
    final first = widget.items.where((i) => i.code == widget.selected.first);
    return first.isEmpty ? 'physical' : first.first.area;
  }

  SurveyItem? _item(String code) {
    for (final i in widget.items) {
      if (i.code == code) return i;
    }
    return null;
  }

  void _toggle(String code) {
    if (!_codes.contains(code) && _codes.length >= maxItemCodes) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('분류는 $maxItemCodes개까지 고를 수 있어요.')),
      );
      return;
    }
    setState(() => _codes.contains(code) ? _codes.remove(code) : _codes.add(code));
  }

  @override
  Widget build(BuildContext context) {
    final areaItems = widget.items.where((i) => i.area == _area).toList();
    return SheetFrame(
      title: '분류 바꾸기',
      children: [
        const _Label('영역'),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final area in _areas)
              SelectChip(
                label: areaLabels[area]!,
                selected: _area == area,
                onTap: () => setState(() {
                  _area = area;
                  if (area == 'uncat') _codes.clear();
                }),
              ),
          ],
        ),
        if (_codes.isNotEmpty) ...[
          _Label('고른 항목 ${_codes.length}개'),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final code in _codes)
                InputChip(
                  label: Text(_item(code)?.path ?? code, style: const TextStyle(fontSize: 14)),
                  onDeleted: () => setState(() => _codes.remove(code)),
                  deleteButtonTooltipMessage: '빼기',
                  backgroundColor: AppColors.mint,
                  side: BorderSide.none,
                  shape: const StadiumBorder(),
                ),
            ],
          ),
        ],
        if (_area == 'uncat')
          const Padding(
            padding: EdgeInsets.only(top: 20),
            child: Text(
              '분류 없이 저장해요. 기록지에는 미분류로 들어가요.',
              style: TextStyle(fontSize: 16, color: AppColors.text),
            ),
          )
        else ...[
          const _Label('항목'),
          for (final item in areaItems)
            InkWell(
              onTap: () => _toggle(item.code),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Row(
                  children: [
                    Icon(
                      _codes.contains(item.code) ? Icons.check_circle : Icons.radio_button_unchecked,
                      color: _codes.contains(item.code) ? AppColors.primaryGlow : AppColors.subtext,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        item.label,
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: AppColors.text),
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
        const SizedBox(height: 24),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(List<String>.of(_codes)),
          style: sheetButtonStyle(),
          child: const Text('적용'),
        ),
      ],
    );
  }
}

// ── 출처 ──

Future<String?> showSourceSheet(BuildContext context, {required String current}) =>
    showFamilySheet<String>(context, (_) => _SourceSheet(current: current));

class _SourceSheet extends StatefulWidget {
  const _SourceSheet({required this.current});

  final String current;

  @override
  State<_SourceSheet> createState() => _SourceSheetState();
}

class _SourceSheetState extends State<_SourceSheet> {
  late String _source = widget.current;

  @override
  Widget build(BuildContext context) {
    return SheetFrame(
      title: '출처 바꾸기',
      children: [
        const SizedBox(height: 16),
        Wrap(
          spacing: 8,
          children: [
            for (final e in sourceLabels.entries)
              SelectChip(label: e.value, selected: _source == e.key, onTap: () => setState(() => _source = e.key)),
          ],
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_source),
          style: sheetButtonStyle(),
          child: const Text('적용'),
        ),
      ],
    );
  }
}

// ── 증상 고치기 ──

class SymptomEdit {
  const SymptomEdit({required this.timeBand, required this.count, required this.note});

  final String timeBand;
  final int count;
  final String note;
}

Future<SymptomEdit?> showSymptomEditSheet(BuildContext context, RecordSymptom symptom) =>
    showFamilySheet<SymptomEdit>(context, (_) => _SymptomEditSheet(symptom: symptom));

class _SymptomEditSheet extends StatefulWidget {
  const _SymptomEditSheet({required this.symptom});

  final RecordSymptom symptom;

  @override
  State<_SymptomEditSheet> createState() => _SymptomEditSheetState();
}

class _SymptomEditSheetState extends State<_SymptomEditSheet> {
  static const _maxCount = 20;

  late String _band = widget.symptom.timeBand;
  late int _count = widget.symptom.count;
  late final _note = TextEditingController(text: widget.symptom.note ?? '');

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SheetFrame(
        title: '${widget.symptom.label} 고치기',
        children: [
          const _Label('언제였나요?'),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final e in timeBandLabels.entries)
                SelectChip(label: e.value, selected: _band == e.key, onTap: () => setState(() => _band = e.key)),
            ],
          ),
          const _Label('횟수'),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton.outlined(
                icon: const Icon(Icons.remove),
                tooltip: '한 번 줄이기',
                onPressed: _count > 1 ? () => setState(() => _count = (_count - 1).clamp(1, _maxCount)) : null,
              ),
              SizedBox(
                width: 110,
                child: Text(
                  '$_count번',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: AppColors.text),
                ),
              ),
              IconButton.outlined(
                icon: const Icon(Icons.add),
                tooltip: '한 번 늘리기',
                onPressed:
                    _count < _maxCount ? () => setState(() => _count = (_count + 1).clamp(1, _maxCount)) : null,
              ),
            ],
          ),
          const _Label('메모 (선택)'),
          TextField(
            controller: _note,
            minLines: 2,
            maxLines: 4,
            maxLength: 500,
            style: const TextStyle(fontSize: 16, color: AppColors.text),
            decoration: InputDecoration(
              counterText: '',
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(
              SymptomEdit(timeBand: _band, count: _count, note: _note.text.trim()),
            ),
            style: sheetButtonStyle(),
            child: const Text('저장'),
          ),
        ],
      ),
    );
  }
}

// ── 기록지에서 제외 ──

enum ExcludeChoice { exclude, reclassify }

/// Figma: 이 기록을 기록지에서 뺄까요? / 분류 바꾸기 · 기록지에서 제외. 바깥 누름 → null
Future<ExcludeChoice?> showExcludeDialog(BuildContext context) {
  return showDialog<ExcludeChoice>(
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
            const Text(
              '이 기록을 기록지에서 뺄까요?',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            const SizedBox(height: 12),
            const Text(
              '삭제되지 않아요. 현황판과 기록지에서만 빠지고, 원문은 그대로 보관돼요.',
              style: TextStyle(fontSize: 16, color: AppColors.subtext, height: 1.6),
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(ExcludeChoice.reclassify),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.primary,
                      side: const BorderSide(color: AppColors.primaryGlow),
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    child: const Text('분류 바꾸기'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).pop(ExcludeChoice.exclude),
                    style: sheetButtonStyle(),
                    child: const Text('기록지에서 제외', maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}
