import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../../shared/widgets/step_progress.dart';

/// 휴대폰 번호 인증 (A-ON-001, 온보딩 1단계)
///
/// 흐름: 번호 입력 → 인증번호 받기 (Supabase 문자) → 6자리 입력 → 다음
///   → 로그인 세션 저장 → GET /v1/auth/me → 다음 단계 화면
/// - 인증번호 유효 3분 (기능명세서), 다시 받기는 보낸 뒤 60초부터 (Supabase 기본 제한)
/// - 6칸 = 입력칸 1개 + 표시만 6칸 (붙여넣기·문자 자동 입력 지원)
class PhoneScreen extends StatefulWidget {
  const PhoneScreen({super.key, this.authApi});

  /// 테스트용 교체 (기본: 실제 Supabase·백엔드)
  final AuthApi? authApi;

  @override
  State<PhoneScreen> createState() => _PhoneScreenState();
}

class _PhoneScreenState extends State<PhoneScreen> {
  static const _codeLength = 6;
  static const _validFor = Duration(minutes: 3);
  static const _resendAfter = Duration(seconds: 60);

  late final AuthApi _auth = widget.authApi ?? AuthApi();
  final _phoneController = TextEditingController();
  final _codeController = TextEditingController();
  final _codeFocus = FocusNode();

  Timer? _timer;
  Duration _remaining = Duration.zero;

  /// 인증번호를 보낸 번호 (+82 형식). 번호 바꾸면 다시 받기
  String? _sentTo;
  bool _sending = false;
  bool _verifying = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _codeController.addListener(() => setState(() {}));
    _codeFocus.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    _codeFocus.dispose();
    super.dispose();
  }

  String get _digits => _phoneController.text.replaceAll(RegExp(r'\D'), '');

  /// 010·011·016~019 + 7~8자리
  bool get _phoneValid => RegExp(r'^01[016789]\d{7,8}$').hasMatch(_digits);

  /// 010-1234-5678 → +821012345678. 번호 미완성 → null
  String? get _e164 => _phoneValid ? '+82${_digits.substring(1)}' : null;

  bool get _expired => _sentTo != null && _remaining == Duration.zero;

  bool get _canResend => _remaining <= _validFor - _resendAfter;

  bool get _canSend => _phoneValid && !_sending && (_sentTo == null || _canResend || _sentTo != _e164);

  bool get _canSubmit =>
      _sentTo != null && _sentTo == _e164 && !_expired && _codeController.text.length == _codeLength && !_verifying;

  Future<void> _sendCode() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final phone = _e164!;
      await _auth.sendPhoneOtp(phone);
      if (!mounted) return;
      _codeController.clear();
      _sentTo = phone;
      _startTimer();
      _codeFocus.requestFocus();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _startTimer() {
    _timer?.cancel();
    final until = DateTime.now().add(_validFor);
    _remaining = _validFor;
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      final left = until.difference(DateTime.now());
      setState(() => _remaining = left.isNegative ? Duration.zero : left);
      if (left.isNegative) timer.cancel();
    });
  }

  Future<void> _submit() async {
    setState(() {
      _verifying = true;
      _error = null;
    });
    try {
      await _auth.verifyPhoneOtp(_sentTo!, _codeController.text);
      final me = await _auth.fetchMe();
      if (mounted) context.go(me.nextRoute);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
      _codeController.clear();
      _codeFocus.requestFocus();
    } finally {
      if (mounted) setState(() => _verifying = false);
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
          onPressed: () => context.canPop() ? context.pop() : context.go('/login'),
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
                    const StepProgress(current: 2),
                    const SizedBox(height: 36),
                    const _IconBadge(icon: Icons.phone_outlined),
                    const SizedBox(height: 16),
                    Text(
                      '휴대폰 번호를\n입력해주세요',
                      style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                            color: AppColors.text,
                            fontWeight: FontWeight.w700,
                            height: 1.5,
                          ),
                    ),
                    const SizedBox(height: 20),
                    _phoneField(),
                    if (_sentTo != null) ...[
                      const SizedBox(height: 28),
                      const Text(
                        '인증번호 6자리',
                        style: TextStyle(fontSize: 15, color: AppColors.subtext),
                      ),
                      const SizedBox(height: 10),
                      _codeBoxes(),
                      const SizedBox(height: 14),
                      _status(),
                    ],
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: FilledButton(
                onPressed: _canSubmit ? _submit : null,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  disabledBackgroundColor: AppColors.track,
                  disabledForegroundColor: AppColors.subtext,
                  minimumSize: const Size.fromHeight(52),
                  shape: const StadiumBorder(),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                child: _verifying
                    ? const SizedBox.square(dimension: 22, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('다음'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 번호 입력 + 인증번호 받기 (Figma: 높이 62, 모서리 12, 테두리 primary)
  Widget _phoneField() {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 4, 8, 4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.primary),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _phoneController,
              keyboardType: TextInputType.phone,
              autofillHints: const [AutofillHints.telephoneNumber],
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, _PhoneFormatter()],
              onChanged: (_) => setState(() => _error = null),
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w500, color: Colors.black),
              decoration: const InputDecoration(
                border: InputBorder.none,
                hintText: '010-0000-0000',
                hintStyle: TextStyle(color: AppColors.subtext),
              ),
            ),
          ),
          TextButton(
            onPressed: _canSend ? _sendCode : null,
            style: TextButton.styleFrom(
              backgroundColor: AppColors.mint,
              foregroundColor: AppColors.text,
              disabledBackgroundColor: AppColors.track,
              shape: const StadiumBorder(),
              padding: const EdgeInsets.symmetric(horizontal: 12),
              textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
            ),
            child: _sending
                ? const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : Text(_sentTo == null ? '인증번호 받기' : '다시 받기'),
          ),
        ],
      ),
    );
  }

  /// 6칸 (표시용) 위에 투명 입력칸 1개
  Widget _codeBoxes() {
    final code = _codeController.text;
    return Stack(
      children: [
        Row(
          children: [
            for (var i = 0; i < _codeLength; i++) ...[
              if (i > 0) const SizedBox(width: 10),
              Expanded(
                child: AspectRatio(
                  aspectRatio: 48 / 58,
                  child: Container(
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: _codeFocus.hasFocus && i == code.length.clamp(0, _codeLength - 1)
                            ? AppColors.primary
                            : AppColors.border,
                      ),
                    ),
                    child: Text(
                      i < code.length ? code[i] : '',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                        color: AppColors.primary,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
        Positioned.fill(
          child: Opacity(
            opacity: 0,
            child: TextField(
              controller: _codeController,
              focusNode: _codeFocus,
              enabled: !_expired,
              keyboardType: TextInputType.number,
              autofillHints: const [AutofillHints.oneTimeCode],
              maxLength: _codeLength,
              showCursor: false,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              onChanged: (value) {
                if (value.length == _codeLength && _canSubmit) _submit();
              },
              decoration: const InputDecoration(counterText: '', border: InputBorder.none),
            ),
          ),
        ),
      ],
    );
  }

  Widget _status() {
    if (_expired) {
      return const Text(
        '인증번호 시간이 지났어요. 다시 받아 주세요.',
        style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: AppColors.subtext),
      );
    }
    final minutes = _remaining.inMinutes;
    final seconds = (_remaining.inSeconds % 60).toString().padLeft(2, '0');
    return Row(
      children: [
        const Icon(Icons.check, size: 20, color: AppColors.primary),
        const SizedBox(width: 6),
        Text(
          '인증번호를 보냈어요 ($minutes:$seconds)',
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: AppColors.primary),
        ),
      ],
    );
  }
}

/// 원형 배경 아이콘 (Figma: 지름 48, mint)
class _IconBadge extends StatelessWidget {
  const _IconBadge({required this.icon});

  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 48,
      height: 48,
      decoration: const BoxDecoration(color: AppColors.mint, shape: BoxShape.circle),
      child: Icon(icon, size: 24, color: AppColors.primary),
    );
  }
}

/// 숫자 → 010-1234-5678 (11자리) / 011-123-4567 (10자리)
class _PhoneFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    final digits = newValue.text.length > 11 ? newValue.text.substring(0, 11) : newValue.text;
    final String text;
    if (digits.length <= 3) {
      text = digits;
    } else if (digits.length <= 7) {
      text = '${digits.substring(0, 3)}-${digits.substring(3)}';
    } else {
      final middle = digits.length == 11 ? 7 : 6;
      text = '${digits.substring(0, 3)}-${digits.substring(3, middle)}-${digits.substring(middle)}';
    }
    return TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
  }
}
