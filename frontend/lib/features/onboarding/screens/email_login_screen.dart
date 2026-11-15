import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/auth/auth_api.dart';
import '../../../shared/widgets/step_progress.dart';

/// 이메일 로그인·가입
///
class EmailLoginScreen extends StatefulWidget {
  const EmailLoginScreen({super.key, this.authApi});

  /// 테스트용 교체
  final AuthApi? authApi;

  @override
  State<EmailLoginScreen> createState() => _EmailLoginScreenState();
}

class _EmailLoginScreenState extends State<EmailLoginScreen> {
  late final AuthApi _auth = widget.authApi ?? AuthApi();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _signUp = false;
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  void initState() {
    super.initState();
    _emailController.addListener(() => setState(() {}));
    _passwordController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  String get _email => _emailController.text.trim();

  bool get _valid =>
      RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(_email) &&
      _passwordController.text.length >= 6;

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      if (_signUp) {
        final loggedIn = await _auth.signUpWithEmail(
          _email,
          _passwordController.text,
        );
        if (!loggedIn) {
          if (mounted) {
            setState(() {
              _notice = '메일함에서 인증 링크를 누른 뒤 로그인해 주세요.';
              _signUp = false;
            });
          }
          return;
        }
      } else {
        await _auth.signInWithEmail(_email, _passwordController.text);
      }
      final me = await _auth.fetchMe();
      if (mounted) context.go(me.nextRoute);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toggleMode() {
    setState(() {
      _signUp = !_signUp;
      _error = null;
    });
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
          onPressed: () =>
              context.canPop() ? context.pop() : context.go('/login'),
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
                child: AutofillGroup(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const StepProgress(current: 1),
                      const SizedBox(height: 36),
                      Container(
                        width: 48,
                        height: 48,
                        decoration: const BoxDecoration(
                          color: AppColors.mint,
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(
                          Icons.mail_outline,
                          color: AppColors.primary,
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        _signUp ? '이메일로\n가입해주세요' : '이메일로\n로그인해주세요',
                        style: const TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                          height: 1.5,
                          color: AppColors.text,
                        ),
                      ),
                      const SizedBox(height: 20),
                      _field(
                        controller: _emailController,
                        hint: '이메일',
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [AutofillHints.email],
                      ),
                      const SizedBox(height: 12),
                      _field(
                        controller: _passwordController,
                        hint: '비밀번호 (6자 이상)',
                        obscure: true,
                        autofillHints: [
                          _signUp
                              ? AutofillHints.newPassword
                              : AutofillHints.password,
                        ],
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 12),
                        Text(
                          _error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ],
                      if (_notice != null) ...[
                        const SizedBox(height: 12),
                        Text(
                          _notice!,
                          style: const TextStyle(
                            color: AppColors.primary,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                      const SizedBox(height: 8),
                      TextButton(
                        onPressed: _busy ? null : _toggleMode,
                        style: TextButton.styleFrom(
                          foregroundColor: AppColors.subtext,
                          padding: EdgeInsets.zero,
                        ),
                        child: Text(
                          _signUp ? '이미 가입했어요 · 로그인' : '처음이에요 · 가입하기',
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: FilledButton(
                onPressed: _valid && !_busy ? _submit : null,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.primaryGlow,
                  disabledBackgroundColor: AppColors.track,
                  disabledForegroundColor: AppColors.subtext,
                  minimumSize: const Size.fromHeight(52),
                  shape: const StadiumBorder(),
                  textStyle: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                child: _busy
                    ? const SizedBox.square(
                        dimension: 22,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Text(_signUp ? '가입하기' : '로그인'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String hint,
    TextInputType? keyboardType,
    bool obscure = false,
    Iterable<String>? autofillHints,
  }) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      obscureText: obscure,
      autofillHints: autofillHints,
      style: const TextStyle(fontSize: 18, color: AppColors.text),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: AppColors.subtext),
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 18,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.primary),
        ),
      ),
    );
  }
}
