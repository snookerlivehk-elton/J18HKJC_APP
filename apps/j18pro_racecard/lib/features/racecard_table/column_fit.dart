import 'package:flutter/material.dart';

/// Scroll-column width for one race.
///
/// Web `COL_FIT` (`dataToRulePx: 2`, `rulePx: 1`) plus `fitScrollColWidths`:
/// the column is the longest header or cell, ceiled, with 2px on the left of
/// the text, 2px from the text to the 1px rule, and that rule on the right.
/// Shorter cells stay centered inside that box, so only the longest value
/// sits exactly 2px off the divider.
abstract final class ColumnFit {
  static const dataToRulePx = 2.0;
  static const rulePx = 1.0;

  /// Left gap + content-to-divider gap + rule.
  static const chromePx = dataToRulePx + dataToRulePx + rulePx;

  static double measure(String text, TextStyle style, TextScaler textScaler) {
    final painter = TextPainter(
      text: TextSpan(text: text, style: style),
      textDirection: TextDirection.ltr,
      textScaler: textScaler,
      maxLines: 1,
    )..layout();
    return painter.width;
  }

  static double widthFor({
    required String header,
    required Iterable<String> cells,
    required TextStyle style,
    TextScaler textScaler = TextScaler.noScaling,
  }) {
    var maxText = measure(header, style, textScaler);
    for (final cell in cells) {
      final width = measure(cell, style, textScaler);
      if (width > maxText) maxText = width;
    }
    return (maxText + chromePx).ceilToDouble();
  }
}
