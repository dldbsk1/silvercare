import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:silvercare/main.dart';

void main() {
  // 테스트 중 글꼴 내려받기 X
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('로그인 없음 → 시작하기 화면: 문구 + 로그인 버튼 4개 + 이메일 (개발용)', (tester) async {
    await tester.pumpWidget(const SilverCareApp());
    await tester.pump();
    await tester.pump();

    expect(find.textContaining('부모님의 평소가'), findsOneWidget);
    for (final label in [
      '카카오로 시작하기',
      '구글로 시작하기',
      '네이버로 시작하기',
      '휴대폰 번호로 시작하기',
      '이메일로 시작하기 (개발용)',
    ]) {
      expect(find.text(label), findsOneWidget);
    }

    await tester.tap(find.text('카카오로 시작하기'));
    await tester.pump();
    expect(find.text('카카오 로그인은 준비 중이에요.'), findsOneWidget);
  });

  testWidgets('휴대폰 번호로 시작하기 → 휴대폰 인증 화면', (tester) async {
    await tester.pumpWidget(const SilverCareApp());
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('휴대폰 번호로 시작하기'));
    await tester.pumpAndSettle();
    expect(find.text('휴대폰 번호를\n입력해주세요'), findsOneWidget);
  });

  testWidgets('이메일로 시작하기 → 이메일 로그인 화면', (tester) async {
    await tester.pumpWidget(const SilverCareApp());
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('이메일로 시작하기 (개발용)'));
    await tester.pumpAndSettle();
    expect(find.text('이메일로\n로그인해주세요'), findsOneWidget);
  });
}
