import 'package:flutter/material.dart';

/// Color tokens copied from `static/racecard_board.html` `:root` and
/// `html[data-theme="dark"]`. Phase 0 does not port the full stylesheet.
@immutable
class J18Tokens extends ThemeExtension<J18Tokens> {
  const J18Tokens({
    required this.nav,
    required this.nav2,
    required this.navTop,
    required this.page,
    required this.text,
    required this.muted,
    required this.blue,
    required this.green,
    required this.orange,
    required this.line,
    required this.shell,
  });

  /// Web `--nav`.
  final Color nav;

  /// Web `--nav-2`.
  final Color nav2;

  /// Top stop of the steel-blue top bar gradient.
  final Color navTop;

  /// Web `--page`.
  final Color page;

  /// Web `--text`.
  final Color text;

  /// Web `--muted`.
  final Color muted;

  /// Web `--blue` (race pills). Kept for later phases.
  final Color blue;

  /// Web `--green`.
  final Color green;

  /// Web `--orange`.
  final Color orange;

  /// Web `--line`.
  final Color line;

  /// Page chrome outside the phone column (`body` background).
  final Color shell;

  static const light = J18Tokens(
    nav: Color(0xFF3D5A80),
    nav2: Color(0xFF334B6B),
    navTop: Color(0xFF4A6A90),
    page: Color(0xFFEEF1F5),
    text: Color(0xFF2C3340),
    muted: Color(0xFF8A93A3),
    blue: Color(0xFF5BA3D9),
    green: Color(0xFF5CB85C),
    orange: Color(0xFFE88B2A),
    line: Color(0xFFE4E7EC),
    shell: Color(0xFFD8DEE6),
  );

  static const dark = J18Tokens(
    nav: Color(0xFF6A86A8),
    nav2: Color(0xFF2A3D58),
    navTop: Color(0xFF3A5474),
    page: Color(0xFF1A1F27),
    text: Color(0xFFE6EAF0),
    muted: Color(0xFF9AA3B2),
    blue: Color(0xFF6EB3E0),
    green: Color(0xFF5CB86A),
    orange: Color(0xFFE39A45),
    line: Color(0xFF3A4250),
    shell: Color(0xFF12161C),
  );

  @override
  J18Tokens copyWith({
    Color? nav,
    Color? nav2,
    Color? navTop,
    Color? page,
    Color? text,
    Color? muted,
    Color? blue,
    Color? green,
    Color? orange,
    Color? line,
    Color? shell,
  }) {
    return J18Tokens(
      nav: nav ?? this.nav,
      nav2: nav2 ?? this.nav2,
      navTop: navTop ?? this.navTop,
      page: page ?? this.page,
      text: text ?? this.text,
      muted: muted ?? this.muted,
      blue: blue ?? this.blue,
      green: green ?? this.green,
      orange: orange ?? this.orange,
      line: line ?? this.line,
      shell: shell ?? this.shell,
    );
  }

  @override
  J18Tokens lerp(ThemeExtension<J18Tokens>? other, double t) {
    if (other is! J18Tokens) return this;
    return J18Tokens(
      nav: Color.lerp(nav, other.nav, t)!,
      nav2: Color.lerp(nav2, other.nav2, t)!,
      navTop: Color.lerp(navTop, other.navTop, t)!,
      page: Color.lerp(page, other.page, t)!,
      text: Color.lerp(text, other.text, t)!,
      muted: Color.lerp(muted, other.muted, t)!,
      blue: Color.lerp(blue, other.blue, t)!,
      green: Color.lerp(green, other.green, t)!,
      orange: Color.lerp(orange, other.orange, t)!,
      line: Color.lerp(line, other.line, t)!,
      shell: Color.lerp(shell, other.shell, t)!,
    );
  }
}

class J18Theme {
  const J18Theme._();

  static ThemeData light() => _build(Brightness.light, J18Tokens.light);

  static ThemeData dark() => _build(Brightness.dark, J18Tokens.dark);

  static ThemeData _build(Brightness brightness, J18Tokens tokens) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: tokens.nav,
      brightness: brightness,
    ).copyWith(
      primary: tokens.nav,
      onPrimary: Colors.white,
      secondary: tokens.green,
      onSecondary: Colors.white,
      tertiary: tokens.orange,
      onTertiary: Colors.white,
      surface: tokens.page,
      onSurface: tokens.text,
      outline: tokens.line,
    );

    const title = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 17,
      fontWeight: FontWeight.w700,
      letterSpacing: 1.02,
      color: Colors.white,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: tokens.page,
      extensions: [tokens],
      fontFamily: 'Noto Sans TC',
      fontFamilyFallback: const [
        'PingFang TC',
        'Microsoft JhengHei',
        'Noto Sans CJK TC',
        'sans-serif',
      ],
      appBarTheme: const AppBarTheme(
        foregroundColor: Colors.white,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: true,
        toolbarHeight: 56,
        titleTextStyle: title,
      ),
    );
  }
}
