import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// 가족 탭 바텀시트 열기 (공통 모양: 흰 바탕, 위 모서리 둥글게, 뒤 어둡게)
Future<T?> showFamilySheet<T>(BuildContext context, WidgetBuilder builder) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    barrierColor: AppColors.text.withValues(alpha: 0.45),
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
    ),
    builder: builder,
  );
}

/// 첫 글자 원 (초대 대기 → 점선 테두리)
class MemberAvatar extends StatelessWidget {
  const MemberAvatar({super.key, required this.text, this.dashed = false});

  final String text;
  final bool dashed;

  @override
  Widget build(BuildContext context) {
    final label = Text(
      text,
      style: TextStyle(
        fontSize: 16,
        color: dashed ? AppColors.text : AppColors.subtext,
      ),
    );
    if (dashed) {
      return CustomPaint(
        painter: _DashedCirclePainter(),
        child: SizedBox(width: 60, height: 60, child: Center(child: label)),
      );
    }
    return Container(
      width: 60,
      height: 60,
      alignment: Alignment.center,
      decoration: const BoxDecoration(
        color: Color(0xFFE9F1EF),
        shape: BoxShape.circle,
      ),
      child: label,
    );
  }
}

class _DashedCirclePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.subtext.withValues(alpha: 0.6)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    final rect = Offset.zero & size;
    const dashes = 24;
    const sweep = 2 * math.pi / dashes;
    for (var i = 0; i < dashes; i++) {
      canvas.drawArc(rect.deflate(0.5), i * sweep, sweep * 0.55, false, paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class OutlineBadge extends StatelessWidget {
  const OutlineBadge(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.primary),
      ),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w700,
          color: AppColors.primary,
        ),
      ),
    );
  }
}

/// 바텀시트 공통 틀 (손잡이 + 제목)
class SheetFrame extends StatelessWidget {
  const SheetFrame({super.key, required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 44,
                height: 5,
                decoration: BoxDecoration(
                  color: AppColors.track,
                  borderRadius: BorderRadius.circular(3),
                ),
              ),
            ),
            const SizedBox(height: 22),
            Text(
              title,
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.text,
              ),
            ),
            ...children,
          ],
        ),
      ),
    );
  }
}


/// 권한 시트 (Figma: "형의 권한" / 기록 가능 · 보기만 / 적용)
class RoleSheet extends StatefulWidget {
  const RoleSheet({super.key, required this.name, required this.current});

  final String name;
  final String current;

  @override
  State<RoleSheet> createState() => _RoleSheetState();
}

class _RoleSheetState extends State<RoleSheet> {
  late String _role = widget.current;

  static const _options = [
    ('writer', '기록 가능', '기록을 남기고 고칠 수 있어요'),
    ('viewer', '보기만', '기록을 볼 수만 있어요'),
  ];

  @override
  Widget build(BuildContext context) {
    return SheetFrame(
      title: '${widget.name}의 권한',
      children: [
        const SizedBox(height: 12),
        RadioGroup<String>(
          groupValue: _role,
          onChanged: (v) => setState(() => _role = v ?? _role),
          child: Column(
            children: [
              for (final (value, title, desc) in _options)
                RadioListTile<String>(
                  value: value,
                  contentPadding: EdgeInsets.zero,
                  activeColor: AppColors.primaryGlow,
                  title: Text(
                    title,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.text,
                    ),
                  ),
                  subtitle: Text(
                    desc,
                    style: const TextStyle(
                      fontSize: 16,
                      color: AppColors.subtext,
                    ),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_role),
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
          child: const Text('적용'),
        ),
      ],
    );
  }
}
