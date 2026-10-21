import 'package:j18pro_racecard/features/horse_sheet/horse_detail.dart';

/// Web `jtCollabDemoOf`.
///
/// There is no partnership export on api_jjjc. The sheet is a deterministic
/// demo from the horse number, the race, and the two names.
class JtCollabDemo {
  const JtCollabDemo({
    required this.jockey,
    required this.trainer,
    required this.summary,
    required this.races,
  });

  final String jockey;
  final String trainer;
  final String summary;
  final List<JtCollabRace> races;

  bool get hasPeople => jockey.isNotEmpty || trainer.isNotEmpty;

  String get pair =>
      '${jockey.isEmpty ? '—' : jockey} × ${trainer.isEmpty ? '—' : trainer}';
}

class JtCollabRace {
  const JtCollabRace({
    required this.date,
    required this.course,
    required this.dist,
    required this.finish,
  });

  final String date;
  final String course;
  final String dist;
  final int finish;

  String get finishLabel => '第$finish名';
}

const _courses = ['沙田', '跑馬地', '沙田', '跑馬地'];
const _dists = ['1200米', '1400米', '1650米', '1000米', '1800米'];

/// Web `splitPersonName`: allowance stripped, blanks and dashes dropped.
String jtPersonName(String? raw) {
  final name = splitJockey(raw).name.trim();
  if (name.isEmpty || name == '—' || name == '-') return '';
  return name;
}

JtCollabDemo jtCollabDemo({
  required int horseNo,
  required int raceNum,
  required String? jockeyRaw,
  required String? trainerRaw,
}) {
  final jockey = jtPersonName(jockeyRaw);
  final trainer = jtPersonName(trainerRaw);
  final seed =
      (horseNo * 17 + raceNum * 11 + jockey.length * 3 + trainer.length * 5)
          .abs();
  final runs = 6 + (seed % 10);
  final wins = seed % 4;
  final seconds = (seed >> 1) % 3;
  final thirds = (seed >> 2) % 3;
  final places = wins + seconds + thirds;
  final winPct = runs == 0 ? '0.0' : ((wins / runs) * 100).toStringAsFixed(1);
  final placePct = runs == 0
      ? '0.0'
      : ((places / runs) * 100).toStringAsFixed(1);
  final shown = runs < 6 ? runs : 6;
  final races = <JtCollabRace>[
    for (var i = 0; i < shown; i++)
      JtCollabRace(
        date: _date(seed, i),
        course: _courses[(seed + i) % _courses.length],
        dist: _dists[(seed + i * 2) % _dists.length],
        finish: _finish(seed, i),
      ),
  ];
  return JtCollabDemo(
    jockey: jockey,
    trainer: trainer,
    summary:
        '近季合作：$runs 仗 · $wins冠 $seconds亞 $thirds季 · 勝率 $winPct% · 位置率 $placePct%',
    races: races,
  );
}

String _date(int seed, int index) {
  final month = ((9 - (index % 6)) + 11) % 12 + 1;
  final day = 3 + ((seed + index * 5) % 24);
  return '2026-${month.toString().padLeft(2, '0')}-${day.toString().padLeft(2, '0')}';
}

int _finish(int seed, int index) {
  final roll = (seed + index * 9) % 11;
  if (roll == 0) return 1;
  if (roll == 1) return 2;
  if (roll == 2) return 3;
  return 4 + (roll % 7);
}
