import 'package:flutter/material.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_table/column_fit.dart';

/// Header and cells share this style so measured width matches paint.
const racecardCellStyle = TextStyle(
  fontFamily: 'Noto Sans TC',
  fontSize: 13,
  fontWeight: FontWeight.w400,
);

/// Phase 2 right-hand columns. Later phases can pass a different list.
const kPhase2ScrollColumns = <ScrollColumn>[
  ScrollColumn(id: 'draw', header: '檔位', text: drawColumnText),
  ScrollColumn(id: 'win', header: '獨贏', text: winColumnText),
  ScrollColumn(id: 'place', header: '位置', text: placeColumnText),
  ScrollColumn(id: 'form6', header: '近績', text: formColumnText),
];

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
