import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/race_calendar/race_fixtures.dart';

/// Web race calendar. Closing the sheet applies the selected day.
class RaceCalendarSheet extends ConsumerStatefulWidget {
  const RaceCalendarSheet({super.key});

  @override
  ConsumerState<RaceCalendarSheet> createState() => _RaceCalendarSheetState();
}

class _RaceCalendarSheetState extends ConsumerState<RaceCalendarSheet> {
  late int _year;
  late int _month;
  late String _selected;
  late RaceCalendarScope _scope;
  var _committed = false;
  var _allowPop = false;

  @override
  void initState() {
    super.initState();
    final state = ref.read(racecardControllerProvider).asData?.value;
    _selected = state?.meeting.date ?? '2026-09-23';
    _scope = state?.calendarScope ?? RaceCalendarScope.hk;
    final parts = _selected.split('-');
    _year = int.tryParse(parts.first) ?? 2026;
    _month = parts.length > 1 ? (int.tryParse(parts[1]) ?? 9) : 9;
  }

  /// Applies the day, then allows the route to pop. [PopScope] blocks the
  /// first pop so the barrier and the close button share this path.
  Future<void> _requestClose() async {
    if (_committed) return;
    _committed = true;
    await ref
        .read(racecardControllerProvider.notifier)
        .selectDate(_selected, scope: _scope);
    if (!mounted) return;
    setState(() => _allowPop = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop();
    });
  }

  void _shiftMonth(int delta) {
    setState(() {
      _month += delta;
      if (_month < 1) {
        _month = 12;
        _year -= 1;
      } else if (_month > 12) {
        _month = 1;
        _year += 1;
      }
    });
  }

  void _setScope(RaceCalendarScope scope) {
    if (scope == _scope) return;
    setState(() {
      _scope = scope;
      if (fixtureOn(_selected, scope) == null) {
        _selected = nearestFixtureDate(_selected, scope) ?? _selected;
      }
      final parts = _selected.split('-');
      if (parts.length == 3) {
        _year = int.parse(parts[0]);
        _month = int.parse(parts[1]);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final height = MediaQuery.sizeOf(context).height * 0.78;
    return PopScope(
      canPop: _allowPop,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _requestClose();
      },
      child: SafeArea(
        child: SizedBox(
          key: const Key('race-calendar'),
          height: height,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Column(
              children: [
                Row(
                  children: [
                    IconButton(
                      key: const Key('cal-prev'),
                      tooltip: '上一個月',
                      onPressed: () => _shiftMonth(-1),
                      icon: const Icon(Icons.chevron_left),
                    ),
                    Expanded(
                      child: Text(
                        '$_year年$_month月',
                        key: const Key('cal-title'),
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontFamily: 'Noto Sans TC',
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: tokens.text,
                        ),
                      ),
                    ),
                    IconButton(
                      key: const Key('cal-next'),
                      tooltip: '下一個月',
                      onPressed: () => _shiftMonth(1),
                      icon: const Icon(Icons.chevron_right),
                    ),
                    IconButton(
                      key: const Key('cal-close'),
                      tooltip: '關閉',
                      onPressed: _requestClose,
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                const Text(
                  '賽期',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 8),
                SegmentedButton<RaceCalendarScope>(
                  segments: const [
                    ButtonSegment(
                      value: RaceCalendarScope.hk,
                      label: Text('香港馬', key: Key('cal-scope-hk')),
                    ),
                    ButtonSegment(
                      value: RaceCalendarScope.os,
                      label: Text('外國馬', key: Key('cal-scope-os')),
                    ),
                  ],
                  selected: {_scope},
                  onSelectionChanged: (next) => _setScope(next.first),
                  style: const ButtonStyle(
                    visualDensity: VisualDensity.compact,
                    textStyle: WidgetStatePropertyAll(
                      TextStyle(fontFamily: 'Noto Sans TC', fontSize: 13),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                const Row(
                  children: [
                    _Wday('日'),
                    _Wday('一'),
                    _Wday('二'),
                    _Wday('三'),
                    _Wday('四'),
                    _Wday('五'),
                    _Wday('六'),
                  ],
                ),
                Expanded(
                  child: SingleChildScrollView(
                    child: _MonthGrid(
                      year: _year,
                      month: _month,
                      scope: _scope,
                      selected: _selected,
                      onSelect: (iso) => setState(() => _selected = iso),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                if (_scope == RaceCalendarScope.hk)
                  const _Legend(
                    label: '香港馬賽日圖例',
                    items: [
                      _LegendItem('st-day', '沙田·日馬'),
                      _LegendItem('st-night', '沙田·夜馬'),
                      _LegendItem('hv-day', '跑馬地·日馬'),
                      _LegendItem('hv-night', '跑馬地·夜馬'),
                    ],
                  )
                else
                  const _Legend(
                    label: '外國馬賽日圖例',
                    items: [
                      _LegendItem('os-uk', '英國'),
                      _LegendItem('os-au', '澳洲'),
                      _LegendItem('os-fr', '法國'),
                      _LegendItem('os-ae', '阿聯酋'),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MonthGrid extends StatelessWidget {
  const _MonthGrid({
    required this.year,
    required this.month,
    required this.scope,
    required this.selected,
    required this.onSelect,
  });

  final int year;
  final int month;
  final RaceCalendarScope scope;
  final String selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final cells = _cells();
    return Column(
      children: [
        for (var week = 0; week < 6; week++)
          Row(
            children: [
              for (var day = 0; day < 7; day++)
                Expanded(child: cells[week * 7 + day]),
            ],
          ),
      ],
    );
  }

  List<Widget> _cells() {
    final first = DateTime(year, month, 1);
    final startPad = first.weekday % 7;
    final daysInMonth = DateTime(year, month + 1, 0).day;
    final prevDays = DateTime(year, month, 0).day;
    return [
      for (var i = 0; i < 42; i++)
        _cellAt(
          i,
          startPad: startPad,
          daysInMonth: daysInMonth,
          prevDays: prevDays,
        ),
    ];
  }

  Widget _cellAt(
    int index, {
    required int startPad,
    required int daysInMonth,
    required int prevDays,
  }) {
    var y = year;
    var m = month;
    late int d;
    var mute = false;
    if (index < startPad) {
      d = prevDays - startPad + index + 1;
      m = month - 1;
      if (m < 1) {
        m = 12;
        y -= 1;
      }
      mute = true;
    } else if (index >= startPad + daysInMonth) {
      d = index - (startPad + daysInMonth) + 1;
      m = month + 1;
      if (m > 12) {
        m = 1;
        y += 1;
      }
      mute = true;
    } else {
      d = index - startPad + 1;
    }
    final iso =
        '$y-${m.toString().padLeft(2, '0')}-${d.toString().padLeft(2, '0')}';
    final fixtures = mute
        ? const <RaceFixture>[]
        : [
            for (final fixture in fixturesFor(scope))
              if (fixture.date == iso) fixture,
          ];
    return _DayCell(
      day: d,
      iso: iso,
      mute: mute,
      fixtures: fixtures,
      selected: iso == selected,
      onSelect: onSelect,
    );
  }
}

class _DayCell extends StatelessWidget {
  const _DayCell({
    required this.day,
    required this.iso,
    required this.mute,
    required this.fixtures,
    required this.selected,
    required this.onSelect,
  });

  final int day;
  final String iso;
  final bool mute;
  final List<RaceFixture> fixtures;
  final bool selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final race = fixtures.isNotEmpty;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Padding(
      padding: const EdgeInsets.all(1),
      child: Material(
        color: race
            ? (selected
                  ? (dark ? const Color(0xFF2A3D58) : const Color(0xFFEEF3F8))
                  : (dark ? const Color(0xFF323A46) : const Color(0xFFF5F7FA)))
            : Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: selected
              ? BorderSide(color: tokens.nav, width: 1.5)
              : BorderSide.none,
        ),
        child: InkWell(
          key: race ? Key('cal-day-$iso') : null,
          onTap: race ? () => onSelect(iso) : null,
          borderRadius: BorderRadius.circular(8),
          child: SizedBox(
            height: 40,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  '$day',
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 13,
                    height: 1,
                    fontWeight: race ? FontWeight.w700 : FontWeight.w400,
                    color: mute
                        ? (dark
                              ? const Color(0xFF5A6370)
                              : const Color(0xFFC0C6D0))
                        : tokens.text,
                  ),
                ),
                if (race)
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      for (final fixture in fixtures)
                        Container(
                          width: 5,
                          height: 5,
                          margin: const EdgeInsets.symmetric(horizontal: 1),
                          decoration: BoxDecoration(
                            color: markColor(fixtureMarkClass(fixture)),
                            shape: BoxShape.circle,
                          ),
                        ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Wday extends StatelessWidget {
  const _Wday(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Text(
        label,
        textAlign: TextAlign.center,
        style: const TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 12,
          color: Color(0xFF8A93A3),
        ),
      ),
    );
  }
}

class _LegendItem {
  const _LegendItem(this.mark, this.label);

  final String mark;
  final String label;
}

class _Legend extends StatelessWidget {
  const _Legend({required this.label, required this.items});

  final String label;
  final List<_LegendItem> items;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: label,
      child: Wrap(
        spacing: 10,
        runSpacing: 4,
        children: [
          for (final item in items)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: markColor(item.mark),
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 4),
                Text(
                  item.label,
                  style: const TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 11,
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

Color markColor(String mark) {
  return switch (mark) {
    'st-night' => const Color(0xFF1F6F8F),
    'hv-day' => const Color(0xFF5A8F6B),
    'hv-night' => const Color(0xFF3D5A80),
    'os-uk' => const Color(0xFF5B6B9A),
    'os-au' => const Color(0xFFB08A3C),
    'os-fr' => const Color(0xFF6B8F9A),
    'os-ae' => const Color(0xFF8A6A9A),
    _ => const Color(0xFFD4A017),
  };
}
