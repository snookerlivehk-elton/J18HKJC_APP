/// Web `synthReviewOverlay` text, demo seed, and note save rules.
///
/// The main-table dual line (評述 / 筆記) stays on the Web board for now.
/// It is not a sortable column and is not painted on the racecard table.
library;

import 'package:j18pro_racecard/domain/meeting.dart';

/// Web `SYNTH_REVIEW_DEMO`.
const kSynthReviewDemo =
    '在第五班1200米全天候跑道賽事中表現穩定，模型勝率達22.56%，預測排名第一，顯示其競爭力不俗。'
    '然而，從外檔11起步可能增加比賽難度，且近績顯示其起步後居後列，直路時才略為追前，顯示其需要較長距離發揮。';

/// Web `HORSE_NOTE_DEMO`.
const kHorseNoteDemo = '這匹馬上一仗發力基本在後期';

/// Web `ensureHorseNoteDemo` runs on the bundled snapshot only.
const synthReviewDemoDate = '2026-09-23';

/// One saved or demo history row.
class HorseNoteEntry {
  const HorseNoteEntry({
    required this.id,
    required this.date,
    required this.text,
    required this.finish,
    required this.jockey,
    required this.dist,
    required this.course,
  });

  final String id;
  final String date;
  final String text;
  final String finish;
  final String jockey;
  final String dist;
  final String course;

  Map<String, String> toJson() {
    return {
      'id': id,
      'date': date,
      'text': text,
      'finish': finish,
      'jockey': jockey,
      'dist': dist,
      'course': course,
    };
  }

  static HorseNoteEntry? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final text = _stringOf(raw['text']).trim();
    if (text.isEmpty) return null;
    return HorseNoteEntry(
      id: _stringOf(raw['id']),
      date: _stringOf(raw['date']),
      text: text,
      finish: _stringOf(raw['finish']),
      jockey: _stringOf(raw['jockey']),
      dist: _stringOf(raw['dist']),
      course: _stringOf(raw['course']),
    );
  }
}

/// Latest note plus history for one horse.
///
/// A stored record replaces the demo seed for that horse, including when
/// [text] is empty.
class HorseNoteRecord {
  const HorseNoteRecord({required this.text, required this.history});

  static const empty = HorseNoteRecord(text: '', history: []);

  final String text;
  final List<HorseNoteEntry> history;

  /// Web `horseNoteOf`: the saved line, otherwise the newest history row.
  String get openingDraft {
    final trimmed = text.trim();
    if (trimmed.isNotEmpty) return trimmed;
    if (history.isEmpty) return '';
    return history.first.text;
  }

  Map<String, Object> toJson() {
    return {
      'text': text,
      'history': [for (final entry in history) entry.toJson()],
    };
  }
}

/// `date:raceNum:horseNo`, for example `2026-09-23:5:5`.
String horseNoteStorageKey(String date, int raceNum, int horseNo) {
  return '$date:$raceNum:$horseNo';
}

/// Web `synthReviewOf`. Scratched horses and the snapshot's race-1 horse 2
/// stay empty. Everyone else gets the horse name plus [kSynthReviewDemo].
String synthReviewText({
  required Runner runner,
  required int raceNum,
  required String meetingDate,
}) {
  if (runner.scratched) return '';
  if (meetingDate == synthReviewDemoDate && raceNum == 1 && runner.no == 2) {
    return '';
  }
  final name = runner.name.trim().isEmpty ? '該駒' : runner.name.trim();
  return '$name$kSynthReviewDemo';
}

/// Web `formatHorseNoteDate`.
String formatHorseNoteDate(String? raw) {
  final source = raw?.trim() ?? '';
  if (source.isEmpty) return '';
  final iso = RegExp(r'^(\d{4})-(\d{1,2})-(\d{1,2})').firstMatch(source);
  if (iso != null) {
    return '${iso.group(3)!.padLeft(2, '0')}/'
        '${iso.group(2)!.padLeft(2, '0')}/'
        '${iso.group(1)}';
  }
  final slash = RegExp(r'^(\d{1,2})/(\d{1,2})/(\d{4})$').firstMatch(source);
  if (slash != null) {
    return '${slash.group(1)!.padLeft(2, '0')}/'
        '${slash.group(2)!.padLeft(2, '0')}/'
        '${slash.group(3)}';
  }
  return source;
}

/// Web `horseNoteMetaParts`, joined with `·`.
String horseNoteMeta(HorseNoteEntry entry) {
  final parts = <String>[];
  final date = formatHorseNoteDate(entry.date);
  if (date.isNotEmpty) parts.add(date);
  if (entry.finish.isNotEmpty) {
    final digits = RegExp(r'^\d+$').hasMatch(entry.finish);
    parts.add(digits ? '第${entry.finish}名' : entry.finish);
  }
  if (entry.jockey.isNotEmpty) parts.add(entry.jockey);
  if (entry.dist.isNotEmpty) parts.add(entry.dist);
  if (entry.course.isNotEmpty) parts.add(entry.course);
  if (parts.isEmpty) return '歷史筆記';
  return parts.join('·');
}

/// Distance label from a race meta line, such as `1650米`.
String raceDistLabel(String meta) {
  final match = RegExp(r'(\d{3,4})\s*米').firstMatch(meta);
  if (match == null) return '';
  return '${match.group(1)}米';
}

/// Web course short name from `courseLabel`.
String noteCourseOf(String courseLabel) {
  if (courseLabel.contains('沙田')) return '沙田';
  if (courseLabel.contains('跑馬地') || courseLabel.contains('谷')) {
    return '跑馬地';
  }
  return courseLabel;
}

/// Demo history for horses that exist on the snapshot. Missing horses
/// (Web race 2 horse 4 is not in the 3-race fixture) return null.
HorseNoteRecord? demoHorseNote({
  required String date,
  required int raceNum,
  required int horseNo,
}) {
  if (date != synthReviewDemoDate) return null;
  return switch ((raceNum, horseNo)) {
    (1, 3) => HorseNoteRecord(
      text: kHorseNoteDemo,
      history: [
        _demo('2026-09-23', kHorseNoteDemo, '2', '霍宏聲', '1650米', '跑馬地', 'd1'),
        _demo('2026-08-17', '中後段加速尚可，宜避快步場', '5', '潘頓', '1200米', '沙田', 'd2'),
        _demo('2026-07-01', '初出未盡全力，後續值得跟進', '8', '何澤堯', '1400米', '沙田', 'd3'),
      ],
    ),
    (1, 11) => HorseNoteRecord(
      text: kHorseNoteDemo,
      history: [
        _demo('2026-09-23', kHorseNoteDemo, '1', '潘頓', '1650米', '跑馬地', 'd1'),
        _demo('2026-09-03', '外檔起步後居後，直路才略追', '4', '潘頓', '1200米', '沙田', 'd2'),
      ],
    ),
    (5, 5) => HorseNoteRecord(
      text: kHorseNoteDemo,
      history: [
        _demo('2026-09-23', kHorseNoteDemo, '1', '周俊樂', '1650米', '跑馬地', 'd1'),
      ],
    ),
    _ => null,
  };
}

HorseNoteEntry _demo(
  String date,
  String text,
  String finish,
  String jockey,
  String dist,
  String course,
  String id,
) {
  return HorseNoteEntry(
    id: id,
    date: date,
    text: text,
    finish: finish,
    jockey: jockey,
    dist: dist,
    course: course,
  );
}

/// Saved map wins. Otherwise the demo seed. Scratched horses stay empty.
HorseNoteRecord resolveHorseNote({
  required Map<String, HorseNoteRecord> saved,
  required String date,
  required int raceNum,
  required int horseNo,
  required bool scratched,
}) {
  if (scratched) return HorseNoteRecord.empty;
  final key = horseNoteStorageKey(date, raceNum, horseNo);
  final stored = saved[key];
  if (stored != null) return stored;
  return demoHorseNote(date: date, raceNum: raceNum, horseNo: horseNo) ??
      HorseNoteRecord.empty;
}

/// Web `saveSynthHorseNote`. Empty text clears the latest line and does not
/// prepend. The same text on the same date replaces the older row.
HorseNoteRecord applyHorseNoteSave({
  required HorseNoteRecord current,
  required String draft,
  required String meetingDate,
  required Runner runner,
  required String raceMeta,
  required String courseLabel,
  required String id,
}) {
  final text = draft.trim();
  if (text.isEmpty) {
    return HorseNoteRecord(text: '', history: current.history);
  }
  final entry = HorseNoteEntry(
    id: id,
    date: meetingDate,
    text: text,
    finish: runner.finish == null ? '' : '${runner.finish}',
    jockey: runner.jockey,
    dist: raceDistLabel(raceMeta),
    course: noteCourseOf(courseLabel),
  );
  final kept = [
    for (final item in current.history)
      if (!(item.text.trim() == text && item.date == meetingDate)) item,
  ];
  return HorseNoteRecord(text: text, history: [entry, ...kept]);
}

String _stringOf(Object? value) {
  if (value == null) return '';
  return value.toString();
}
