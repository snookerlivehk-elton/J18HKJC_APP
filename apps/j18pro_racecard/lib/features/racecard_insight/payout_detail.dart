import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';

/// Web `raceHasPayout`.
bool raceHasPayout(Race? race) {
  if (race == null) return false;
  if (race.paid || race.payoutReady || race.hasDividend) return true;
  final dividends = race.dividends;
  if (dividends == null) return false;
  return dividends.isNotEmpty;
}

class PayoutRow {
  const PayoutRow({required this.combo, required this.pay});

  final String combo;
  final num? pay;
}

class PayoutSection {
  const PayoutSection({required this.pool, required this.rows});

  final String pool;
  final List<PayoutRow> rows;
}

/// `Number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })`.
String fmtPayoutAmt(num? value) {
  if (value == null) return '—';
  final number = value.toDouble();
  if (number.isNaN || number.isInfinite) return '—';
  final negative = number < 0;
  final fixed = number.abs().toStringAsFixed(2);
  final pieces = fixed.split('.');
  final digits = pieces[0];
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return '${negative ? '-' : ''}$buffer.${pieces[1]}';
}

String pairCombo(Object? a, Object? b, {required bool ordered}) {
  if (a == null || b == null) return '';
  if (ordered) return '$a,$b';
  final left = num.parse('$a');
  final right = num.parse('$b');
  final sorted = [left, right]..sort();
  return '${_comboToken(sorted[0])},${_comboToken(sorted[1])}';
}

String trioCombo(Object? a, Object? b, Object? c, {required bool ordered}) {
  if (a == null || b == null || c == null) return '';
  if (ordered) return '$a,$b,$c';
  final sorted = [num.parse('$a'), num.parse('$b'), num.parse('$c')]..sort();
  return sorted.map(_comboToken).join(',');
}

String quartetCombo(
  Object? a,
  Object? b,
  Object? c,
  Object? d, {
  required bool ordered,
}) {
  if (a == null || b == null || c == null || d == null) return '';
  if (ordered) return '$a,$b,$c,$d';
  final sorted = [
    num.parse('$a'),
    num.parse('$b'),
    num.parse('$c'),
    num.parse('$d'),
  ]..sort();
  return sorted.map(_comboToken).join(',');
}

String _comboToken(num value) {
  if (value == value.roundToDouble()) return value.toInt().toString();
  return value.toString();
}

/// Web `buildPayoutDetailSections`. Real dividends win; otherwise the demo pools.
List<PayoutSection> buildPayoutDetailSections(Race race) {
  final dividends = race.dividends;
  if (dividends != null && dividends.isNotEmpty) {
    final order = <String>[];
    final grouped = <String, List<PayoutRow>>{};
    for (final dividend in dividends) {
      final rows = grouped.putIfAbsent(dividend.pool, () {
        order.add(dividend.pool);
        return <PayoutRow>[];
      });
      rows.add(PayoutRow(combo: dividend.combo, pay: dividend.pay));
    }
    return [
      for (final pool in order)
        if (grouped[pool]!.isNotEmpty)
          PayoutSection(pool: pool, rows: grouped[pool]!),
    ];
  }
  final nos = [for (final no in payoutFinishNosForRace(race)) '$no'];
  if (nos.isEmpty) return const [];
  final a = nos[0];
  final b = nos.length > 1 ? nos[1] : null;
  final c = nos.length > 2 ? nos[2] : null;
  final d = nos.length > 3 ? nos[3] : null;
  final sections = <PayoutSection>[
    PayoutSection(
      pool: '獨贏',
      rows: [PayoutRow(combo: a, pay: 118.5)],
    ),
  ];
  if (b != null && c != null) {
    sections.add(
      PayoutSection(
        pool: '位置',
        rows: [
          PayoutRow(combo: a, pay: 28),
          PayoutRow(combo: b, pay: 15.5),
          PayoutRow(combo: c, pay: 16),
        ],
      ),
    );
  }
  if (b != null) {
    sections.add(
      PayoutSection(
        pool: '連贏',
        rows: [PayoutRow(combo: pairCombo(a, b, ordered: false), pay: 205.5)],
      ),
    );
  }
  if (b != null && c != null) {
    sections.add(
      PayoutSection(
        pool: '位置Q',
        rows: [
          PayoutRow(combo: pairCombo(a, b, ordered: false), pay: 75),
          PayoutRow(combo: pairCombo(a, c, ordered: false), pay: 63.5),
          PayoutRow(combo: pairCombo(b, c, ordered: false), pay: 31.5),
        ],
      ),
    );
    sections.add(
      PayoutSection(
        pool: '二重彩',
        rows: [PayoutRow(combo: pairCombo(a, b, ordered: true), pay: 539)],
      ),
    );
    sections.add(
      PayoutSection(
        pool: '三重彩',
        rows: [PayoutRow(combo: trioCombo(a, b, c, ordered: false), pay: 1597)],
      ),
    );
    sections.add(
      PayoutSection(
        pool: '單T',
        rows: [PayoutRow(combo: trioCombo(a, b, c, ordered: true), pay: 182)],
      ),
    );
  }
  if (b != null && c != null && d != null) {
    sections.add(
      PayoutSection(
        pool: '四連環',
        rows: [
          PayoutRow(combo: quartetCombo(a, b, c, d, ordered: false), pay: 601),
        ],
      ),
    );
    sections.add(
      PayoutSection(
        pool: '四重彩',
        rows: [
          PayoutRow(combo: quartetCombo(a, b, c, d, ordered: true), pay: 15907),
        ],
      ),
    );
  }
  return sections;
}
