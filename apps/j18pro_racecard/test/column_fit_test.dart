import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/features/racecard_table/column_fit.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const style = racecardMeasureStyle;

  test('column width is the longest text plus the fixed gap and rule', () {
    const sample = '10/11/7/1/7/10';
    final text = ColumnFit.measure(sample, style, TextScaler.noScaling);
    final width = ColumnFit.widthFor(
      header: '1',
      cells: [sample],
      style: style,
    );
    expect(width, (text + ColumnFit.chromePx).ceilToDouble());
    expect(width - text, inInclusiveRange(ColumnFit.chromePx, ColumnFit.chromePx + 1));
  });

  test('header text can set the column when it is wider than the cells', () {
    const header = 'WWWWWW';
    final headerWidth = ColumnFit.measure(header, style, TextScaler.noScaling);
    final width = ColumnFit.widthFor(
      header: header,
      cells: const ['1'],
      style: style,
    );
    expect(width, (headerWidth + ColumnFit.chromePx).ceilToDouble());
    expect(
      width,
      greaterThan(
        ColumnFit.widthFor(header: '1', cells: const ['1'], style: style),
      ),
    );
  });

  test('a longer cell widens the column and a short one does not', () {
    final narrow = ColumnFit.widthFor(
      header: '近績',
      cells: const ['1'],
      style: style,
    );
    final wide = ColumnFit.widthFor(
      header: '近績',
      cells: const ['1', '10/11/7/1/7/10'],
      style: style,
    );
    expect(wide, greaterThan(narrow));
    expect(ColumnFit.chromePx, 5);
    expect(ColumnFit.dataToRulePx, 2);
    expect(ColumnFit.rulePx, 1);
  });
}

const racecardMeasureStyle = TextStyle(
  fontFamily: 'Noto Sans TC',
  fontSize: 13,
  fontWeight: FontWeight.w400,
);
