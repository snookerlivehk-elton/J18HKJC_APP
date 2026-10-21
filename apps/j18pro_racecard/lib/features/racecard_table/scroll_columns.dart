import 'package:flutter/material.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/horse_sheet/horse_detail.dart';
import 'package:j18pro_racecard/features/racecard_table/column_fit.dart';

/// Header and cells share this style so measured width matches paint.
const racecardCellStyle = TextStyle(
  fontFamily: 'Noto Sans TC',
  fontSize: 13,
  fontWeight: FontWeight.w400,
);

/// Phase 2 right-hand columns. The sort sheet can show a different order.
const kPhase2ScrollColumns = <ScrollColumn>[
  ScrollColumn(id: 'draw', header: '檔位', text: drawColumnText),
  ScrollColumn(id: 'win', header: '獨贏', text: winColumnText),
  ScrollColumn(id: 'place', header: '位置', text: placeColumnText),
  ScrollColumn(id: 'form6', header: '近績', text: formColumnText),
];

/// Fields the table can paint. Water, flow, tip marks, and synth review stay out.
const kAllScrollColumns = <ScrollColumn>[
  ...kPhase2ScrollColumns,
  ScrollColumn(id: 'hw', header: '負磅', text: hwColumnText),
  ScrollColumn(id: 'jockey', header: '騎師', text: jockeyColumnText),
  ScrollColumn(id: 'trainer', header: '練馬師', text: trainerColumnText),
  ScrollColumn(id: 'age', header: '年齡', text: ageColumnText),
  ScrollColumn(id: 'rating', header: '評分', text: ratingColumnText),
  ScrollColumn(id: 'career', header: '出道至今', text: careerColumnText),
  ScrollColumn(id: 'gear', header: '配備', text: gearColumnText),
  ScrollColumn(id: 'dam', header: '母系', text: damColumnText),
  ScrollColumn(id: 'sire', header: '父系', text: sireColumnText),
  ScrollColumn(id: 'damsire', header: '外祖父', text: damsireColumnText),
  ScrollColumn(id: 'owner', header: '馬主', text: ownerColumnText),
  ScrollColumn(id: 'prize', header: '獎金', text: prizeColumnText),
];

ScrollColumn? scrollColumnById(String id) {
  for (final column in kAllScrollColumns) {
    if (column.id == id) return column;
  }
  return null;
}

class ScrollColumn {
  const ScrollColumn({
    required this.id,
    required this.header,
    required this.text,
  });

  final String id;
  final String header;
  final String Function(Runner runner) text;
}

String drawColumnText(Runner runner) => '${runner.draw}';

String winColumnText(Runner runner) {
  if (runner.scratched) return '—';
  return formatOdds(runner.win);
}

String placeColumnText(Runner runner) {
  if (runner.scratched) return '—';
  return formatOdds(runner.place);
}

String formColumnText(Runner runner) {
  final form = runner.form6;
  if (form != null && form.isNotEmpty) return form;
  final recent = runner.recent;
  if (recent != null && recent.isNotEmpty) return recent;
  return '—';
}

String hwColumnText(Runner runner) => withDelta(runner.hw, hwDeltaOf(runner));

String jockeyColumnText(Runner runner) => jockeyLine(runner);

String trainerColumnText(Runner runner) => sheetText(runner.trainer);

String ageColumnText(Runner runner) => sheetText(runner.age);

String ratingColumnText(Runner runner) {
  return withDelta(runner.rating, fmtDelta(runner.rtgDelta));
}

String careerColumnText(Runner runner) => formatCareer(runner.career);

String gearColumnText(Runner runner) => sheetText(runner.gear);

String damColumnText(Runner runner) => sheetText(runner.dam);

String sireColumnText(Runner runner) => sheetText(runner.sire);

String damsireColumnText(Runner runner) => sheetText(runner.damsire);

String ownerColumnText(Runner runner) => sheetText(runner.owner);

String prizeColumnText(Runner runner) => sheetText(runner.prize);

List<double> fitScrollWidths({
  required Race race,
  required TextScaler textScaler,
  List<ScrollColumn> columns = kPhase2ScrollColumns,
  TextStyle style = racecardCellStyle,
}) {
  return [
    for (final column in columns)
      ColumnFit.widthFor(
        header: column.header,
        cells: race.runners.map(column.text),
        style: style,
        textScaler: textScaler,
      ),
  ];
}

/// Remembers right-column widths for one [Race] instance, column list, and scale.
///
/// A horizontal drag rebuilds the table on every pointer move, and a swallowtail
/// tap rebuilds it again. Both used to run [TextPainter] over every cell.
/// [resolve] measures only when the race instance, the column list instance,
/// the text scale, or the style changes. Switching race passes a different
/// [Race] and measures once. The visible rows still rebuild, because the
/// horses changed.
class ScrollWidthCache {
  Race? _race;
  List<ScrollColumn>? _columns;
  double? _scale;
  TextStyle? _style;
  List<double>? _widths;

  List<double> resolve({
    required Race race,
    required TextScaler textScaler,
    required List<ScrollColumn> columns,
    TextStyle style = racecardCellStyle,
  }) {
    final scale = textScaler.scale(1);
    final cached = _widths;
    if (cached != null &&
        identical(_race, race) &&
        identical(_columns, columns) &&
        _scale == scale &&
        _style == style) {
      return cached;
    }
    final widths = fitScrollWidths(
      race: race,
      textScaler: textScaler,
      columns: columns,
      style: style,
    );
    _race = race;
    _columns = columns;
    _scale = scale;
    _style = style;
    _widths = widths;
    return widths;
  }
}
