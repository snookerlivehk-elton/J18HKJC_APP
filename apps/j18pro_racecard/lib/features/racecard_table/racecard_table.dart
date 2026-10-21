import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard_table/row_chrome.dart';
import 'package:j18pro_racecard/features/racecard_table/scroll_columns.dart';
import 'package:j18pro_racecard/features/racecard_table/swallowtail_flag.dart';

const racecardLockWidth = 156.0;
const racecardHeaderHeight = 47.0;
const racecardRowHeight = 49.0;

enum _DragAxis { none, horizontal, vertical }

/// Portrait racecard. The left lock and the right columns share each
/// [ListView] row, so vertical movement cannot drift. Horizontal movement is
/// one offset applied to the header and every body row.
class RacecardTable extends StatefulWidget {
  const RacecardTable({
    required this.race,
    required this.marks,
    required this.onCycleMark,
    this.onOpenHorse,
    this.columns = kPhase2ScrollColumns,
    super.key,
  });

  final Race race;
  final Map<String, int> marks;
  final ValueChanged<int> onCycleMark;
  final ValueChanged<int>? onOpenHorse;
  final List<ScrollColumn> columns;

  @override
  State<RacecardTable> createState() => _RacecardTableState();
}

class _RacecardTableState extends State<RacecardTable> {
  double _offset = 0;
  double _maxOffset = 0;
  Offset? _pointerDown;
  _DragAxis _axis = _DragAxis.none;

  @override
  void didUpdateWidget(RacecardTable oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.race.num != widget.race.num) {
      _offset = 0;
    }
  }

  int _markFor(int horseNo) {
    final mark = widget.marks['${widget.race.num}:$horseNo'] ?? 0;
    if (mark == 1 || mark == 2) return mark;
    return 0;
  }

  void _resetPointer() {
    _pointerDown = null;
    _axis = _DragAxis.none;
  }

  void _onPointerDown(PointerDownEvent event) {
    _pointerDown = event.position;
    _axis = _DragAxis.none;
  }

  void _onPointerMove(PointerMoveEvent event) {
    final origin = _pointerDown;
    if (origin == null) return;
    if (_axis == _DragAxis.none) {
      final delta = event.position - origin;
      if (delta.dx.abs() < kTouchSlop && delta.dy.abs() < kTouchSlop) return;
      _axis = delta.dx.abs() >= delta.dy.abs()
          ? _DragAxis.horizontal
          : _DragAxis.vertical;
    }
    if (_axis != _DragAxis.horizontal || event.delta.dx == 0) return;
    setState(() {
      _offset = (_offset - event.delta.dx).clamp(0.0, _maxOffset);
    });
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final brightness = Theme.of(context).brightness;
    final textScaler = MediaQuery.textScalerOf(context);
    final scale = textScaler.scale(1);
    final headerHeight = racecardHeaderHeight * scale;
    final rowHeight = racecardRowHeight * scale;
    final widths = fitScrollWidths(
      race: widget.race,
      textScaler: textScaler,
      columns: widget.columns,
    );
    final contentWidth = widths.fold<double>(0, (sum, width) => sum + width);
    final dark = brightness == Brightness.dark;
    final headerColor = dark ? RowChrome.darkHeader : RowChrome.lightHeader;
    final headerText = dark
        ? RowChrome.darkHeaderText
        : RowChrome.lightHeaderText;

    return LayoutBuilder(
      builder: (context, constraints) {
        final lockWidth = constraints.maxWidth < racecardLockWidth + 48
            ? (constraints.maxWidth * 0.62).clamp(96.0, racecardLockWidth)
            : racecardLockWidth;
        final viewport = (constraints.maxWidth - lockWidth).clamp(
          0.0,
          double.infinity,
        );
        _maxOffset = (contentWidth - viewport).clamp(0.0, double.infinity);
        if (_offset > _maxOffset) _offset = _maxOffset;
        final offset = _offset;

        return Listener(
          onPointerDown: _onPointerDown,
          onPointerMove: _onPointerMove,
          onPointerUp: (_) => _resetPointer(),
          onPointerCancel: (_) => _resetPointer(),
          child: Column(
            children: [
              _TableBand(
                height: headerHeight,
                color: headerColor,
                lineColor: tokens.line,
                lockWidth: lockWidth,
                scroll: _ScrollPane(
                  paneKey: const Key('scroll-header'),
                  viewportWidth: viewport,
                  contentWidth: contentWidth,
                  offset: offset,
                  child: _ScrollCells(
                    widths: widths,
                    height: headerHeight,
                    texts: [for (final column in widget.columns) column.header],
                    style: racecardCellStyle.copyWith(color: headerText),
                    ruleColor: tokens.line,
                  ),
                ),
                child: Text(
                  '馬匹',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: racecardCellStyle.copyWith(color: headerText),
                ),
              ),
              Expanded(
                child: widget.race.runners.isEmpty
                    ? const Center(
                        child: Text(
                          '暫無馬匹',
                          key: Key('empty-runners'),
                          style: TextStyle(
                            fontFamily: 'Noto Sans TC',
                            fontSize: 15,
                          ),
                        ),
                      )
                    : ListView.builder(
                        key: const Key('runner-list'),
                        itemCount: widget.race.runners.length,
                        itemExtent: rowHeight,
                        itemBuilder: (context, index) {
                          final runner = widget.race.runners[index];
                          final mark = _markFor(runner.no);
                          final chrome = RowChrome.resolve(
                            mark: mark,
                            alt: index.isOdd,
                            brightness: brightness,
                          );
                          return RowBand(
                            key: Key('row-${widget.race.num}-${runner.no}'),
                            color: chrome.background,
                            lineColor: tokens.line,
                            accent: chrome.accent,
                            child: _RunnerRow(
                              raceNum: widget.race.num,
                              runner: runner,
                              mark: mark,
                              flagColor: chrome.flag,
                              rowHeight: rowHeight,
                              lockWidth: lockWidth,
                              viewportWidth: viewport,
                              contentWidth: contentWidth,
                              offset: offset,
                              widths: widths,
                              columns: widget.columns,
                              tokens: tokens,
                              onCycleMark: () => widget.onCycleMark(runner.no),
                              onOpenHorse: widget.onOpenHorse == null
                                  ? null
                                  : () => widget.onOpenHorse!(runner.no),
                            ),
                          );
                        },
                      ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _TableBand extends StatelessWidget {
  const _TableBand({
    required this.height,
    required this.color,
    required this.lineColor,
    required this.lockWidth,
    required this.scroll,
    required this.child,
  });

  final double height;
  final Color color;
  final Color lineColor;
  final double lockWidth;
  final Widget child;
  final Widget scroll;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color,
        border: Border(bottom: BorderSide(color: lineColor)),
      ),
      child: SizedBox(
        height: height,
        child: Row(
          children: [
            SizedBox(
              width: lockWidth,
              child: Padding(
                padding: const EdgeInsets.only(left: 8),
                child: Align(alignment: Alignment.centerLeft, child: child),
              ),
            ),
            Expanded(child: scroll),
          ],
        ),
      ),
    );
  }
}

class _RunnerRow extends StatelessWidget {
  const _RunnerRow({
    required this.raceNum,
    required this.runner,
    required this.mark,
    required this.flagColor,
    required this.rowHeight,
    required this.lockWidth,
    required this.viewportWidth,
    required this.contentWidth,
    required this.offset,
    required this.widths,
    required this.columns,
    required this.tokens,
    required this.onCycleMark,
    required this.onOpenHorse,
  });

  final int raceNum;
  final Runner runner;
  final int mark;
  final Color flagColor;
  final double rowHeight;
  final double lockWidth;
  final double viewportWidth;
  final double contentWidth;
  final double offset;
  final List<double> widths;
  final List<ScrollColumn> columns;
  final J18Tokens tokens;
  final VoidCallback onCycleMark;
  final VoidCallback? onOpenHorse;

  @override
  Widget build(BuildContext context) {
    final scratched = runner.scratched;
    final nameColor = scratched ? tokens.muted : tokens.text;
    final initialStyle = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 11,
      height: 1.05,
      color: scratched ? tokens.muted : tokens.text,
    );
    return SizedBox(
      height: rowHeight,
      child: Row(
        children: [
          SizedBox(
            key: Key('lock-${runner.no}'),
            width: lockWidth,
            child: Padding(
              padding: const EdgeInsets.only(left: 2, right: 4),
              child: Row(
                children: [
                  SwallowtailFlag(
                    key: Key('flag-$raceNum-${runner.no}'),
                    color: flagColor,
                    mark: mark,
                    onPressed: onCycleMark,
                  ),
                  Expanded(
                    child: InkWell(
                      key: Key('horse-open-${runner.no}'),
                      onTap: onOpenHorse,
                      child: Row(
                        children: [
                          _HorseNo(
                            no: runner.no,
                            scratched: scratched,
                            tokens: tokens,
                          ),
                          const SizedBox(width: 2),
                          Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Text(
                                _initial(runner.jockey),
                                style: initialStyle,
                              ),
                              Text(
                                _initial(runner.trainer),
                                style: initialStyle,
                              ),
                            ],
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  runner.name,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    fontFamily: 'Noto Sans TC',
                                    fontSize: 14,
                                    fontWeight: FontWeight.w700,
                                    color: nameColor,
                                    decoration: scratched
                                        ? TextDecoration.lineThrough
                                        : TextDecoration.none,
                                    decorationColor: tokens.muted,
                                  ),
                                ),
                                if (scratched)
                                  Text(
                                    '已退出',
                                    maxLines: 1,
                                    style: TextStyle(
                                      fontFamily: 'Noto Sans TC',
                                      fontSize: 10,
                                      fontWeight: FontWeight.w700,
                                      color: tokens.muted,
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          Expanded(
            child: _ScrollPane(
              paneKey: Key('scroll-row-${runner.no}'),
              viewportWidth: viewportWidth,
              contentWidth: contentWidth,
              offset: offset,
              child: _ScrollCells(
                widths: widths,
                height: rowHeight,
                texts: [for (final column in columns) column.text(runner)],
                style: racecardCellStyle.copyWith(
                  color: scratched ? tokens.muted : tokens.text,
                ),
                ruleColor: tokens.line,
                faded: scratched,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HorseNo extends StatelessWidget {
  const _HorseNo({
    required this.no,
    required this.scratched,
    required this.tokens,
  });

  final int no;
  final bool scratched;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 24,
      height: 24,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: scratched ? tokens.muted : tokens.nav,
        shape: BoxShape.circle,
      ),
      child: Text(
        '$no',
        style: const TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 13,
          color: Colors.white,
          height: 1,
        ),
      ),
    );
  }
}

class _ScrollPane extends StatelessWidget {
  const _ScrollPane({
    required this.paneKey,
    required this.viewportWidth,
    required this.contentWidth,
    required this.offset,
    required this.child,
  });

  final Key paneKey;
  final double viewportWidth;
  final double contentWidth;
  final double offset;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final width = contentWidth < 1 ? viewportWidth : contentWidth;
    return ClipRect(
      child: OverflowBox(
        alignment: Alignment.centerLeft,
        minWidth: width,
        maxWidth: width,
        child: Transform.translate(
          offset: Offset(-offset, 0),
          child: SizedBox(key: paneKey, width: width, child: child),
        ),
      ),
    );
  }
}

class _ScrollCells extends StatelessWidget {
  const _ScrollCells({
    required this.widths,
    required this.height,
    required this.texts,
    required this.style,
    required this.ruleColor,
    this.faded = false,
  });

  final List<double> widths;
  final double height;
  final List<String> texts;
  final TextStyle style;
  final Color ruleColor;
  final bool faded;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var i = 0; i < texts.length; i++)
          SizedBox(
            width: widths[i],
            height: height,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Padding(
                  padding: const EdgeInsets.only(
                    left: ColumnFitPad.left,
                    right: ColumnFitPad.right,
                  ),
                  child: Center(
                    child: Opacity(
                      opacity: faded ? 0.45 : 1,
                      child: Text(
                        texts[i],
                        maxLines: 1,
                        softWrap: false,
                        overflow: TextOverflow.visible,
                        style: style,
                      ),
                    ),
                  ),
                ),
                Positioned(
                  top: ColumnFitPad.left,
                  bottom: ColumnFitPad.left,
                  right: 0,
                  child: ColoredBox(
                    color: ruleColor,
                    child: const SizedBox(width: ColumnFitPad.rule),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Padding that matches [ColumnFit.chromePx]: 2px left, 2px before a 1px rule.
abstract final class ColumnFitPad {
  static const left = 2.0;
  static const right = 3.0;
  static const rule = 1.0;
}

String _initial(String name) {
  if (name.isEmpty) return '';
  return String.fromCharCode(name.runes.first);
}
