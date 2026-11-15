import 'package:flutter/material.dart';

import '../../app/theme.dart';

/// 온보딩 단계 막대 (Figma: 4칸, 높이 6, 간격 6)
class StepProgress extends StatelessWidget {
  const StepProgress({super.key, required this.current, this.total = 4});

  /// 채울 칸 수 (1부터)
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$total단계 중 $current단계',
      child: Row(
        children: [
          for (var i = 0; i < total; i++) ...[
            if (i > 0) const SizedBox(width: 6),
            Expanded(
              child: Container(
                height: 6,
                decoration: BoxDecoration(
                  color: i < current ? AppColors.primaryGlow : AppColors.track,
                  borderRadius: BorderRadius.circular(3),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
