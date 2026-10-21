import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/water_sheet/water_demo.dart';

/// Web `waterSheet`: one row per horse, hours from latest to earlier.
class WaterSheet extends ConsumerStatefulWidget {
  const WaterSheet({super.key});

  @override
  ConsumerState<WaterSheet> createState() => _WaterSheetState();
}

class _WaterSheetState extends ConsumerState<WaterSheet> {
  int? _focusNo;
  int? _focusCol;
  double _offset = 0;

  void _toggle(int horseNo, int col) {
    setState(() {
      if (_focusNo == horseNo && _focusCol == col) {
        _focusNo = null;
        _focusCol = null;
      } else {
        _focusNo = horseNo;
        _focusCol = col;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final state = ref.watch(racecardControllerProvider).asData?.value;
    final race = state?.currentRace;
    final height = MediaQuery.sizeOf(context).height * 0.88;
    final runners = race == null
        ? const <Runner>[]
        : (List<Runner>.of(race.runners)..sort((a, b) => a.no.compareTo(b.no)));
    return SafeArea(
      child: SizedBox(
        key: const Key('water-sheet'),
        height: height,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '水位',
                          style: TextStyle(
                            fontFamily: 'Noto Sans TC',
                            fontSize: 18,
                            fontWeight: FontWeight.w700,
                            color: tokens.text,
                          ),
                        ),
                        Text(
                          race == null ? '—' : '第${race.num}場 ${race.name}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontFamily: 'Noto Sans TC',
                            fontSize: 12,
                            color: tokens.muted,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Semantics(
                    button: true,
                    label: '關閉水位',
                    child: ExcludeSemantics(
                      child: IconButton(
                        key: const Key('water-close'),
                        tooltip: '關閉水位',
                        onPressed: () => Navigator.of(context).pop(),
                        icon: const Icon(Icons.close),
                      ),
                    ),
                  ),
                ],
              ),
              Text(
                '每格：水位（折扣）＋流量　上獨贏／中位置／下 WP　時段由近到遠　點格高亮後見水位升降',
                style: TextStyle(
                  fontFamily: 'Noto Sans TC',
                  fontSize: 11,
                  color: tokens.muted,
                  height: 1.3,
                ),
              ),
              const SizedBox(height: 6),
              Expanded(
                child: runners.isEmpty || race == null
                    ? const Align(
                        alignment: Alignment.topCenter,
                        child: Text(
                          '暫無馬匹',
                          key: Key('water-empty'),
                          style: TextStyle(
                            fontFamily: 'Noto Sans TC',
                            fontSize: 15,
                          ),
                        ),
                      )
                    : _WaterBoard(
                        race: race,
                        runners: runners,
                        tokens: tokens,
                        offset: _offset,
                        focusNo: _focusNo,
                        focusCol: _focusCol,
                        onOffset: (value) => setState(() => _offset = value),
                        onToggle: _toggle,
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WaterBoard extends StatelessWidget {
  const _WaterBoard({
    required this.race,
    required this.runners,
    required this.tokens,
    required this.offset,
    required this.focusNo,
    required this.focusCol,
    required this.onOffset,
    required this.onToggle,
  });

  final Race race;
  final List<Runner> runners;
  final J18Tokens tokens;
  final double offset;
  final int? focusNo;
  final int? focusCol;
  final ValueChanged<double> onOffset;
  final void Function(int horseNo, int col) onToggle;

  static const _lockWidth = 132.0;
  static const _hourWidth = 78.0;
  static const _rowHeight = 58.0;

  @override
  Widget build(BuildContext context) {
    final labels = waterHourLabels(parseMeetHour(race));
    final contentWidth = labels.length * _hourWidth;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return LayoutBuilder(
      builder: (context, constraints) {
        final viewport = (constraints.maxWidth - _lockWidth).clamp(
          0.0,
          double.infinity,
        );
        final maxOffset = (contentWidth - viewport).clamp(0.0, double.infinity);
        final dx = offset.clamp(0.0, maxOffset);
        return GestureDetector(
          onHorizontalDragUpdate: (details) {
            onOffset((dx - details.delta.dx).clamp(0.0, maxOffset));
          },
          child: ListView(
            children: [
              _band(
                height: 28,
                color: dark ? const Color(0xFF243028) : const Color(0xFFE8F0EC),
                lock: const Text(
                  '馬號／馬名',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                hours: [
                  for (var i = 0; i < labels.length; i++)
                    _HourHead(label: labels[i], width: _hourWidth),
                ],
                dx: dx,
                contentWidth: contentWidth,
              ),
              for (final runner in runners)
                _band(
                  height: _rowHeight,
                  color: _rowColor(
                    runner: runner,
                    dark: dark,
                    selected: focusNo == runner.no,
                  ),
                  lock: _Lock(runner: runner, tokens: tokens),
                  hours: [
                    for (var i = 0; i < labels.length; i++)
                      WaterHourCell(
                        key: Key('water-cell-${runner.no}-$i'),
                        sample: waterHourSample(runner, race.num, i),
                        earlier: i + 1 < labels.length
                            ? waterHourSample(runner, race.num, i + 1)
                            : null,
                        width: _hourWidth,
                        selected: focusNo == runner.no && focusCol == i,
                        onTap: () => onToggle(runner.no, i),
                      ),
                  ],
                  dx: dx,
                  contentWidth: contentWidth,
                ),
            ],
          ),
        );
      },
    );
  }

  Color _rowColor({
    required Runner runner,
    required bool dark,
    required bool selected,
  }) {
    if (selected) {
      return dark ? const Color(0xFF2A3D58) : const Color(0xFFE8F0EC);
    }
    if (runner.scratched) {
      return dark ? const Color(0xFF1A1F27) : const Color(0xFFF4F5F7);
    }
    return Colors.transparent;
  }

  Widget _band({
    required double height,
    required Color color,
    required Widget lock,
    required List<Widget> hours,
    required double dx,
    required double contentWidth,
  }) {
    return ColoredBox(
      color: color,
      child: SizedBox(
        height: height,
        child: Row(
          children: [
            SizedBox(width: _lockWidth, child: lock),
            Expanded(
              child: ClipRect(
                child: OverflowBox(
                  alignment: Alignment.centerLeft,
                  minWidth: contentWidth,
                  maxWidth: contentWidth,
                  child: Transform.translate(
                    offset: Offset(-dx, 0),
                    child: Row(children: hours),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HourHead extends StatelessWidget {
  const _HourHead({required this.label, required this.width});

  final String label;
  final double width;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: width,
      child: Text(
        label,
        textAlign: TextAlign.center,
        style: const TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _Lock extends StatelessWidget {
  const _Lock({required this.runner, required this.tokens});

  final Runner runner;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final scratched = runner.scratched;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${runner.no}  ${scratched || runner.win == null ? '—' : formatOdds(runner.win)}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: scratched ? tokens.muted : tokens.text,
              decoration: scratched ? TextDecoration.lineThrough : null,
            ),
          ),
          Text(
            runner.name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 12,
              color: scratched ? tokens.muted : tokens.text,
            ),
          ),
        ],
      ),
    );
  }
}

class WaterHourCell extends StatelessWidget {
  const WaterHourCell({
    required this.sample,
    required this.earlier,
    required this.width,
    required this.selected,
    required this.onTap,
    super.key,
  });

  final WaterSample sample;
  final WaterSample? earlier;
  final double width;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Material(
      color: selected
          ? (dark ? const Color(0xFF3D6B5C) : const Color(0xFFD5E6DC))
          : Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          width: width,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _Line(
                water: sample.winW,
                flow: sample.winF,
                earlierWater: earlier?.winW,
              ),
              _Line(
                water: sample.plaW,
                flow: sample.plaF,
                earlierWater: earlier?.plaW,
              ),
              _Line(
                water: sample.wpW,
                flow: sample.wpF,
                earlierWater: earlier?.wpW,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line({
    required this.water,
    required this.flow,
    required this.earlierWater,
  });

  final int? water;
  final int? flow;
  final int? earlierWater;

  @override
  Widget build(BuildContext context) {
    final dir = waterTrendDir(water, earlierWater);
    final arrow = dir == 'up'
        ? '↖'
        : dir == 'down'
        ? '↙'
        : '';
    final arrowColor = dir == 'up'
        ? const Color(0xFF2E8B57)
        : dir == 'down'
        ? const Color(0xFFCC453F)
        : const Color(0xFF8A93A3);
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        SizedBox(
          width: 12,
          child: Text(
            arrow,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 9, height: 1.1, color: arrowColor),
          ),
        ),
        Text(
          formatWater(water),
          style: const TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 11,
            height: 1.15,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(width: 3),
        Text(
          formatFlow(flow),
          style: const TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 10,
            height: 1.15,
          ),
        ),
      ],
    );
  }
}
