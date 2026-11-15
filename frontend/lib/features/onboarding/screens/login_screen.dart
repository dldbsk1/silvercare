import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';

/// SCR_A_000 시작하기 (A-ON-001)
///
/// Figma 기준 390×844 → 고정 좌표 대신 화면 크기에 맞춰 배치
/// - 위: 로고 + 문구 / 아래: 로그인 버튼 4개 (간격 8, 좌우 24)
/// - 배경 원형 번짐 2개는 맨 뒤 (Figma에서는 버튼 위에 덮여 있었음 → 버튼 눌림 막지 않게)
///
/// 휴대폰 번호 → /onboarding/phone (Supabase 문자 인증)
/// 이메일 (개발용) → /login/email. 제품 로그인 준비 전 다음 화면 개발용
/// TODO(로그인 연결): Supabase OAuth (카카오·구글) + 앱 딥링크 복귀 설정
///   네이버는 Supabase 기본 공급자 아님 → 별도 OIDC 설정 필요
///
/// 브랜드 로고 (각 사 로그인 버튼 가이드)
///   카카오: 검정 말풍선 심볼 (#000000), 배경 #FEE500
///   네이버: 흰색 N 심볼, 배경 녹색
///   구글: 4색 G (assets/images/google_logo.png), 배경 흰색
class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  void _comingSoon(BuildContext context, String method) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text('$method 로그인은 준비 중이에요.')));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          const _BackgroundGlow(),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: 8),
                  const _Logo(),
                  const SizedBox(height: 59),
                  Text(
                    '부모님의 평소가,\n제대로 전해지도록',
                    style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                      color: AppColors.primary,
                      fontSize: 34,
                      fontWeight: FontWeight.w700,
                      height: 1.6,
                    ),
                  ),
                  const Spacer(),
                  _LoginButton(
                    label: '카카오로 시작하기',
                    color: AppColors.kakao,
                    icon: const CustomPaint(
                      size: Size(20, 18),
                      painter: _KakaoSymbol(),
                    ),
                    onPressed: () => _comingSoon(context, '카카오'),
                  ),
                  const SizedBox(height: 8),
                  _LoginButton(
                    label: '구글로 시작하기',
                    color: Colors.white,
                    icon: const _BrandLogo('google_logo.png'),
                    onPressed: () => _comingSoon(context, '구글'),
                  ),
                  const SizedBox(height: 8),
                  _LoginButton(
                    label: '네이버로 시작하기',
                    color: AppColors.naver,
                    icon: const CustomPaint(
                      size: Size(15, 15),
                      painter: _NaverSymbol(),
                    ),
                    onPressed: () => _comingSoon(context, '네이버'),
                  ),
                  const SizedBox(height: 8),
                  _LoginButton(
                    label: '휴대폰 번호로 시작하기',
                    color: AppColors.mint,
                    onPressed: () => context.push('/onboarding/phone'),
                  ),
                  TextButton(
                    onPressed: () => context.push('/login/email'),
                    style: TextButton.styleFrom(
                      foregroundColor: AppColors.subtext,
                    ),
                    child: const Text('이메일로 시작하기'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 로고 (사람 + 하트) + DAMA
class _Logo extends StatelessWidget {
  const _Logo();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        // TODO(Figma): 로고 SVG/PNG 에셋으로 교체
        const SizedBox(
          width: 48,
          height: 48,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              CircleAvatar(radius: 7, backgroundColor: AppColors.primary),
              Icon(Icons.favorite, size: 30, color: AppColors.primary),
            ],
          ),
        ),
        const SizedBox(width: 9),
        Text(
          'DAMA',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: AppColors.primary,
            fontSize: 20,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

/// 로그인 버튼: 높이 52, 모서리 16, 아이콘 + 글자 가운데 정렬
class _LoginButton extends StatelessWidget {
  const _LoginButton({
    required this.label,
    required this.color,
    required this.onPressed,
    this.icon,
  });

  final String label;
  final Color color;
  final Widget? icon;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return FilledButton(
      onPressed: onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: color,
        foregroundColor: AppColors.text,
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (icon != null) ...[
            SizedBox(width: 22, height: 22, child: Center(child: icon)),
            const SizedBox(width: 8),
          ],
          Text(label),
        ],
      ),
    );
  }
}

/// 소셜 로그인 로고 (assets/images, 22×22 안에 맞춤)
class _BrandLogo extends StatelessWidget {
  const _BrandLogo(this.file);

  final String file;

  @override
  Widget build(BuildContext context) {
    return Image.asset('assets/images/$file', fit: BoxFit.contain);
  }
}

/// 카카오 심볼: 검정 말풍선 (타원 + 왼쪽 아래 꼬리)
class _KakaoSymbol extends CustomPainter {
  const _KakaoSymbol();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final paint = Paint()..color = Colors.black;
    canvas.drawOval(Rect.fromLTWH(0, 0, w, h * 0.82), paint);
    canvas.drawPath(
      Path()
        ..moveTo(w * 0.24, h * 0.62)
        ..lineTo(w * 0.18, h)
        ..lineTo(w * 0.46, h * 0.76)
        ..close(),
      paint,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// 네이버 심볼: 흰색 N (세로 막대 2개 + 대각선)
class _NaverSymbol extends CustomPainter {
  const _NaverSymbol();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    canvas.drawPath(
      Path()
        ..moveTo(0, 0)
        ..lineTo(w * 0.345, 0)
        ..lineTo(w * 0.655, h * 0.46)
        ..lineTo(w * 0.655, 0)
        ..lineTo(w, 0)
        ..lineTo(w, h)
        ..lineTo(w * 0.655, h)
        ..lineTo(w * 0.345, h * 0.54)
        ..lineTo(w * 0.345, h)
        ..lineTo(0, h)
        ..close(),
      Paint()..color = Colors.white,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// 배경 원형 번짐 2개 (Figma: 720px 원, 위 오른쪽 · 아래 왼쪽)
class _BackgroundGlow extends StatelessWidget {
  const _BackgroundGlow();

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    // Figma 390×844 기준 위치를 화면 비율로
    final sx = size.width / 390;
    final sy = size.height / 844;

    return Positioned.fill(
      child: IgnorePointer(
        child: Stack(
          children: [
            _glow(left: -55 * sx, top: -240 * sy),
            _glow(left: -272 * sx, top: 354 * sy),
          ],
        ),
      ),
    );
  }

  Widget _glow({required double left, required double top}) {
    return Positioned(
      left: left,
      top: top,
      child: Container(
        width: 720,
        height: 720,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [
              AppColors.primaryGlow.withValues(alpha: 0.2),
              AppColors.primaryGlow.withValues(alpha: 0),
            ],
          ),
        ),
      ),
    );
  }
}
