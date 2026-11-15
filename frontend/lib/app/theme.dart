import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Figma 색 (화면 코드에 색 값 직접 X → 여기서 꺼내 쓰기)
class AppColors {
  /// 제목·로고·주요 버튼
  static const primary = Color(0xFF215451);

  /// 배경 원형 번짐
  static const primaryGlow = Color(0xFF327D79);

  /// 화면 배경 (따뜻한 흰색)
  static const background = Color(0xFFFAF7F2);

  /// 본문·버튼 글자
  static const text = Color(0xFF293C3B);

  /// 보조 버튼 (휴대폰 번호로 시작하기 등)
  static const mint = Color(0xFFD6E9E5);

  /// 단계 막대 빈 칸 · 비활성 버튼
  static const track = Color(0xFFDCE3E1);

  /// 입력칸 테두리 (기본)
  static const border = Color(0xFFE3E3E0);

  /// 안내 글자 (라벨)
  static const subtext = Color(0xFF4F6360);

  /// 소셜 로그인 브랜드 색
  static const kakao = Color(0xFFFEE500);
  static const naver = Color(0xFF00C44B);
}

/// 공통 테마. 글꼴 Noto Sans KR
///
/// 접근성 기준 (기능명세서 NFR): 본문 16px 이상, 버튼 44px 이상, 대비 4.5:1
class AppTheme {
  static ThemeData light() {
    return ThemeData(
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        primary: AppColors.primary,
        surface: AppColors.background,
        onSurface: AppColors.text,
      ),
      scaffoldBackgroundColor: AppColors.background,
      useMaterial3: true,
      // 글꼴 이름만 (google_fonts TextTheme 형식 → 이 Flutter 버전과 타입 불일치)
      fontFamily: GoogleFonts.notoSansKr().fontFamily,
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(minimumSize: const Size(44, 52)),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(minimumSize: const Size(44, 52)),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(44, 44)),
      ),
    );
  }
}
