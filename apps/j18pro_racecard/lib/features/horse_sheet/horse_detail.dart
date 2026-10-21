import 'package:j18pro_racecard/domain/meeting.dart';

final _allowPattern = RegExp(
  r'^(.*?)[\s\u3000]*([(\uFF08][+\-]?\d+[)\uFF09])$',
);

/// Web `fmtDelta`. Zero and blanks become an empty string.
String fmtDelta(Object? value) {
  if (value == null) return '';
  final raw = value.toString().trim();
  if (raw.isEmpty || raw == '—' || raw == '-') return '';
  final parsed = double.tryParse(raw.replaceFirst(RegExp(r'^\+'), ''));
  if (parsed == null) {
    if (raw == '0' || raw == '+0' || raw == '-0') return '';
    return raw;
  }
  if (parsed == 0) return '';
  final body = parsed == parsed.roundToDouble()
      ? parsed.toInt().toString()
      : parsed.toString();
  return parsed > 0 ? '+$body' : body;
}

/// Web `splitNameAllow`: name plus the allowance in parentheses.
({String name, String delta}) splitJockey(String? raw) {
  final text = (raw ?? '').trim();
  final match = _allowPattern.firstMatch(text);
  if (match == null || (match.group(1) ?? '').trim().isEmpty) {
    return (name: text, delta: '');
  }
  final allow = match.group(2) ?? '';
  final number = RegExp(r'([+\-]?\d+)').firstMatch(allow);
  final parsed = number == null ? null : double.tryParse(number.group(1)!);
  var delta = '';
  if (parsed != null && parsed != 0) {
    final signed = allow.startsWith('(+') || allow.startsWith('（+')
        ? parsed
        : (allow.startsWith('(-') || allow.startsWith('（-') || parsed < 0)
        ? parsed
        : -parsed.abs();
    delta = fmtDelta(signed);
  }
  return (name: match.group(1)!.trim(), delta: delta);
}

/// Web `hwDeltaOf` fallback: the jockey allowance shown as a negative.
String hwDeltaOf(Runner runner) {
  final allow = _allowPattern.firstMatch(runner.jockey.trim());
  if (allow == null) return '';
  final number = RegExp(r'([+\-]?\d+)').firstMatch(allow.group(2) ?? '');
  if (number == null) return '';
  final parsed = double.tryParse(number.group(1)!);
  if (parsed == null || parsed == 0) return '';
  return fmtDelta(parsed > 0 ? -parsed : parsed);
}

String withDelta(Object? base, String delta) {
  if (base == null || base.toString().trim().isEmpty) {
    return delta.isEmpty ? '—' : delta;
  }
  if (delta.isEmpty) return base.toString();
  return '$base（$delta）';
}

/// Web `fmtCareer` for `wins-seconds-thirds-starts`.
String formatCareer(String? raw) {
  final text = (raw ?? '').trim();
  if (text.isEmpty) return '—';
  final modern = RegExp(
    r'^(\d+)\s*[（(]\s*(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d+)\s*[）)]$',
  ).firstMatch(text);
  if (modern != null) {
    return '${modern.group(1)}（${modern.group(2)}-${modern.group(3)}-${modern.group(4)}）';
  }
  final old = RegExp(r'^(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d+)$')
      .firstMatch(text);
  if (old != null) {
    return '${old.group(4)}（${old.group(1)}-${old.group(2)}-${old.group(3)}）';
  }
  return text;
}

String horseWinText(Runner runner) {
  if (runner.scratched || runner.win == null) return '—';
  return formatOdds(runner.win);
}

/// Web `fmtOdds(..., "place")` keeps one decimal.
String horsePlaceText(Runner runner) {
  if (runner.scratched || runner.place == null) return '—';
  return runner.place!.toStringAsFixed(1);
}

String jockeyLine(Runner runner) {
  final split = splitJockey(runner.jockey);
  if (split.name.isEmpty && split.delta.isEmpty) return '—';
  return withDelta(split.name, split.delta);
}

String sheetText(Object? value) {
  if (value == null) return '—';
  final text = value.toString().trim();
  if (text.isEmpty || text == '—') return '—';
  return text;
}
