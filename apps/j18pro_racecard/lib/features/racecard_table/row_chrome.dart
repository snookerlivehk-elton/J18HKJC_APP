import 'package:flutter/material.dart';

/// Row and swallowtail colors copied from `racecard_board.html`.
///
/// Dark selected marks are their own colors (`#e8b04a` / `#5dce7a`). They must
/// not fall through to the idle gray `#8a93a3` (Web 0.2.367).
@immutable
class RowChrome {
  const RowChrome({
    required this.background,
    required this.flag,
    this.accent,
  });

  final Color background;
  final Color flag;

  /// Dark-mode left bar. Null when the row is unmarked.
  final Color? accent;

  static const lightHeader = Color(0xFFEEF3F8);
  static const darkHeader = Color(0xFF2C3542);
  static const lightHeaderText = Color(0xFF111111);
  static const darkHeaderText = Color(0xFFE8ECF2);

  static const lightIdleFlag = Color(0xFFB0B8C4);
  static const lightMark1Flag = Color(0xFFE88B2A);
  static const lightMark2Flag = Color(0xFF5CB85C);
  static const darkIdleFlag = Color(0xFF8A93A3);
  static const darkMark1Flag = Color(0xFFE8B04A);
  static const darkMark2Flag = Color(0xFF5DCE7A);

  static const lightRow = Color(0xFFFFFFFF);
  static const lightAlt = Color(0xFFF4F6F8);
  static const lightMark1 = Color(0xFFFDE8CC);
  static const lightMark1Alt = Color(0xFFF7DCB8);
  static const lightMark2 = Color(0xFFD4EFDF);
  static const lightMark2Alt = Color(0xFFC5E8D3);

  static const darkRow = Color(0xFF1E242D);
  static const darkAlt = Color(0xFF252B34);
  static const darkMark1 = Color(0xFF6B4F1C);
  static const darkMark1Alt = Color(0xFF7A5A22);
  static const darkMark2 = Color(0xFF1F5C3E);
  static const darkMark2Alt = Color(0xFF256B48);

  static RowChrome resolve({
    required int mark,
    required bool alt,
    required Brightness brightness,
  }) {
    final normalized = mark == 1 || mark == 2 ? mark : 0;
    if (brightness == Brightness.dark) {
      return RowChrome(
        background: switch (normalized) {
          1 => alt ? darkMark1Alt : darkMark1,
          2 => alt ? darkMark2Alt : darkMark2,
          _ => alt ? darkAlt : darkRow,
        },
        flag: switch (normalized) {
          1 => darkMark1Flag,
          2 => darkMark2Flag,
          _ => darkIdleFlag,
        },
        accent: switch (normalized) {
          1 => darkMark1Flag,
          2 => darkMark2Flag,
          _ => null,
        },
      );
    }
    return RowChrome(
      background: switch (normalized) {
        1 => alt ? lightMark1Alt : lightMark1,
        2 => alt ? lightMark2Alt : lightMark2,
        _ => alt ? lightAlt : lightRow,
      },
      flag: switch (normalized) {
        1 => lightMark1Flag,
        2 => lightMark2Flag,
        _ => lightIdleFlag,
      },
    );
  }
}

/// Exposed so tests can read the painted row color without a golden.
class RowBand extends StatelessWidget {
  const RowBand({
    required this.color,
    required this.lineColor,
    required this.child,
    this.accent,
    super.key,
  });

  final Color color;
  final Color lineColor;
  final Color? accent;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color,
        border: Border(
          bottom: BorderSide(color: lineColor),
          left: accent == null
              ? BorderSide.none
              : BorderSide(color: accent!, width: 3),
        ),
      ),
      child: child,
    );
  }
}
