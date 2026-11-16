import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// 탈퇴·필수 동의 철회 뒤 데이터 처리 안내 + "내가 쓴 기록도 모두 지우기" 선택
/// ⚖️ 문구·보관 범위: 법률 확인 전 임시 (todo.md)

/// 탈퇴 안내
const withdrawalNotes = [
  '이름, 전화번호, 로그인 정보 같은 계정 정보는 바로 삭제돼요.',
  '내가 녹음한 음성 파일도 함께 삭제돼요.',
  '가족과 함께 쓰는 돌봄 기록(글)은 보관 근거가 있는 범위에서 가족 공간에 남아요.',
  '남은 기록의 작성자는 \'탈퇴한 사용자\'로 표시돼요.',
  '기록에 담긴 내 개인정보는 따로 삭제를 요청할 수 있어요.',
];

/// 필수 동의 철회 안내
const revokeNotes = [
  '동의를 철회하면 기록하고 보는 기능이 멈춰요. 다시 동의하면 이어서 쓸 수 있어요.',
  '내가 쓴 돌봄 기록은 보관 근거가 있는 범위에서 가족 공간에 남아요.',
  '기록에 담긴 내 개인정보는 따로 삭제를 요청할 수 있어요.',
];

/// 반환: 취소 → null / 진행 → 내 기록 지우기 선택 여부
Future<bool?> showDataChoiceDialog(
  BuildContext context, {
  required String title,
  required List<String> notes,
  required String deleteHelp,
  required String action,
}) =>
    showDialog<bool>(
      context: context,
      builder: (_) => _DataChoiceDialog(title: title, notes: notes, deleteHelp: deleteHelp, action: action),
    );

class _DataChoiceDialog extends StatefulWidget {
  const _DataChoiceDialog({
    required this.title,
    required this.notes,
    required this.deleteHelp,
    required this.action,
  });

  final String title;
  final List<String> notes;
  final String deleteHelp;
  final String action;

  @override
  State<_DataChoiceDialog> createState() => _DataChoiceDialogState();
}

class _DataChoiceDialogState extends State<_DataChoiceDialog> {
  bool _deleteRecords = false;

  @override
  Widget build(BuildContext context) {
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
              widget.title,
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: AppColors.text),
            ),
            const SizedBox(height: 16),
            for (final note in widget.notes) DataNote(note),
            const SizedBox(height: 8),
            Material(
              color: _deleteRecords ? AppColors.mint : AppColors.background,
              borderRadius: BorderRadius.circular(16),
              child: CheckboxListTile(
                value: _deleteRecords,
                onChanged: (v) => setState(() => _deleteRecords = v ?? false),
                controlAffinity: ListTileControlAffinity.leading,
                activeColor: Theme.of(context).colorScheme.error,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                title: const Text(
                  '내가 쓴 기록도 모두 지우기',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: AppColors.text),
                ),
                subtitle: Text(
                  widget.deleteHelp,
                  style: const TextStyle(fontSize: 14, height: 1.5, color: AppColors.subtext),
                ),
              ),
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.text,
                      side: const BorderSide(color: AppColors.track),
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    child: const Text('취소'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).pop(_deleteRecords),
                    style: FilledButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.error,
                      minimumSize: const Size.fromHeight(52),
                      shape: const StadiumBorder(),
                      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    child: Text(widget.action),
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

/// 안내 한 줄 (점 + 글)
class DataNote extends StatelessWidget {
  const DataNote(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.only(top: 9, right: 10),
              child: CircleAvatar(radius: 2.5, backgroundColor: AppColors.subtext),
            ),
            Expanded(
              child: Text(text, style: const TextStyle(fontSize: 15, height: 1.6, color: AppColors.subtext)),
            ),
          ],
        ),
      );
}
