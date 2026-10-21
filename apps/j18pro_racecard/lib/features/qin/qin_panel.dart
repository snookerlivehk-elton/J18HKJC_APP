import 'package:flutter/material.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/qin/qin_board.dart';

/// One matrix cell. Odds sit on the upper triangle, the index on the lower.
class QinMatrixCell extends StatelessWidget {
  const QinMatrixCell({
    required this.text,
    required this.tokens,
    required this.dark,
    required this.onTap,
    this.hot = false,
    this.drop = QinDrop.none,
    this.indexBand,
    this.focused = false,
    this.scratched = false,
    super.key,
  });

  final String text;
  final J18Tokens tokens;
  final bool dark;
  final VoidCallback? onTap;
  final bool hot;
  final QinDrop drop;
  final int? indexBand;
  final bool focused;
  final bool scratched;

  @override
  Widget build(BuildContext context) {
    final fill = _fill();
    final fg = fill == null
        ? (scratched ? tokens.muted : tokens.text)
        : Colors.white;
    return Material(
      color: fill ?? tokens.page,
      child: InkWell(
        onTap: onTap,
        child: Container(
          alignment: Alignment.center,
          decoration: BoxDecoration(
            border: Border.all(
              color: focused ? tokens.nav : tokens.line,
              width: focused ? 2 : 0.5,
            ),
          ),
          child: Text(
            text,
            maxLines: 1,
            overflow: TextOverflow.clip,
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 11,
              height: 1,
              color: fg,
              decoration: scratched ? TextDecoration.lineThrough : null,
              decorationColor: tokens.muted,
            ),
          ),
        ),
      ),
    );
  }

  Color? _fill() {
    if (scratched) return null;
    if (hot || indexBand == 85) {
      return dark ? const Color(0xFFC94A3D) : const Color(0xFFE74C3C);
    }
    if (drop == QinDrop.drop20 || indexBand == 87) return tokens.green;
    if (drop == QinDrop.drop50 || indexBand == 89) {
      return dark ? const Color(0xFFD4924A) : const Color(0xFFC47A3A);
    }
    return null;
  }
}

/// Web `qinPanel`, under the horse rows. Not a board sheet.
class QinPanel extends StatefulWidget {
  const QinPanel({required this.race, super.key});

  final Race race;

  @override
  State<QinPanel> createState() => _QinPanelState();
}

class _QinPanelState extends State<QinPanel> {
  var _mode = QinMode.qin;
  String? _focus;

  @override
  void didUpdateWidget(QinPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.race.num != widget.race.num) _focus = null;
  }

  void _setMode(QinMode mode) {
    if (_mode == mode) return;
    setState(() => _mode = mode);
  }

  void _toggle(String key) {
    setState(() => _focus = _focus == key ? null : key);
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final board = buildQinBoard(widget.race, _mode);
    final place = _mode == QinMode.qpl;
    return Padding(
      key: const Key('qin-panel'),
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (board.nos.length < 2)
            Text(
              '暫無連贏組合',
              key: const Key('qin-empty'),
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 13,
                color: tokens.muted,
              ),
            )
          else
            LayoutBuilder(
              builder: (context, constraints) {
                final count = board.nos.length;
                final avail = constraints.maxWidth < 1
                    ? 200.0
                    : constraints.maxWidth;
                final cell = count <= qinFitRunners
                    ? avail / (count + 1)
                    : avail / (qinFitRunners + 1);
                final table = _matrix(board, cell, tokens, dark);
                if (count <= qinFitRunners) return table;
                return SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: table,
                );
              },
            ),
          const SizedBox(height: 8),
          _Legend(place: place, mode: _mode, tokens: tokens, onMode: _setMode),
        ],
      ),
    );
  }

  Widget _matrix(QinBoard board, double cell, J18Tokens tokens, bool dark) {
    final nos = board.nos;
    final n = nos.length;
    Widget box(Widget child, {double widthFactor = 1}) {
      return SizedBox(width: cell * widthFactor, height: cell, child: child);
    }

    final header = Row(
      children: [
        box(
          _ModeSwitch(mode: _mode, tokens: tokens, onMode: _setMode),
          widthFactor: 2,
        ),
        for (var j = 1; j < n; j++)
          box(
            _Number(
              nos[j],
              scratched: board.scratchedNo(nos[j]),
              tokens: tokens,
              cellKey: Key('qin-col-${nos[j]}'),
            ),
          ),
      ],
    );
    final rows = <Widget>[
      header,
      for (var i = 0; i < n; i++)
        Row(
          children: [
            box(
              i == 0
                  ? _IndexLabel(
                      no: nos[i],
                      scratched: board.scratchedNo(nos[i]),
                      tokens: tokens,
                    )
                  : _Number(
                      nos[i],
                      scratched: board.scratchedNo(nos[i]),
                      tokens: tokens,
                      cellKey: Key('qin-row-${nos[i]}'),
                    ),
            ),
            for (var j = 0; j < n; j++)
              box(_dataCell(board, i, j, tokens, dark)),
          ],
        ),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows);
  }

  Widget _dataCell(QinBoard board, int i, int j, J18Tokens tokens, bool dark) {
    final rowNo = board.nos[i];
    final colNo = board.nos[j];
    if (i == j) {
      return _Number(
        rowNo,
        scratched: board.scratchedNo(rowNo),
        tokens: tokens,
        cellKey: Key('qin-diag-$rowNo'),
      );
    }
    final pair = board.pair(rowNo, colNo);
    final key = qinPairKey(rowNo, colNo);
    final scratched = pair?.scratched ?? true;
    final oddsSide = j > i;
    final index = pair?.index;
    final band = !oddsSide && index != null
        ? (index >= 89
              ? 89
              : index >= 87
              ? 87
              : index >= 85
              ? 85
              : null)
        : null;
    return QinMatrixCell(
      key: Key(oddsSide ? 'qin-odds-$key' : 'qin-idx-$key'),
      text: scratched
          ? '—'
          : (oddsSide ? fmtQinOdds(pair?.odds) : (index?.toString() ?? '—')),
      tokens: tokens,
      dark: dark,
      hot: oddsSide && (pair?.hot ?? false),
      drop: oddsSide ? (pair?.drop ?? QinDrop.none) : QinDrop.none,
      indexBand: band,
      focused: _focus == key,
      scratched: scratched,
      onTap: scratched ? null : () => _toggle(key),
    );
  }
}

class _ModeSwitch extends StatelessWidget {
  const _ModeSwitch({
    required this.mode,
    required this.tokens,
    required this.onMode,
    this.keyed = false,
  });

  final QinMode mode;
  final J18Tokens tokens;
  final ValueChanged<QinMode> onMode;
  final bool keyed;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _ModeButton(
            label: '位置Q',
            selected: mode == QinMode.qpl,
            buttonKey: keyed ? const Key('qin-mode-qpl') : null,
            tokens: tokens,
            onPressed: () => onMode(QinMode.qpl),
          ),
        ),
        Expanded(
          child: _ModeButton(
            label: '正Q',
            selected: mode == QinMode.qin,
            buttonKey: keyed ? const Key('qin-mode-qin') : null,
            tokens: tokens,
            onPressed: () => onMode(QinMode.qin),
          ),
        ),
      ],
    );
  }
}

class _ModeButton extends StatelessWidget {
  const _ModeButton({
    required this.label,
    required this.selected,
    required this.buttonKey,
    required this.tokens,
    required this.onPressed,
  });

  final String label;
  final bool selected;
  final Key? buttonKey;
  final J18Tokens tokens;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      key: buttonKey,
      style: TextButton.styleFrom(
        backgroundColor: selected ? tokens.nav : tokens.shell,
        foregroundColor: selected ? Colors.white : tokens.text,
        padding: EdgeInsets.zero,
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        shape: const RoundedRectangleBorder(),
      ),
      onPressed: onPressed,
      child: Text(
        label,
        maxLines: 1,
        style: const TextStyle(fontFamily: 'Noto Sans TC', fontSize: 10),
      ),
    );
  }
}

class _Number extends StatelessWidget {
  const _Number(
    this.no, {
    required this.scratched,
    required this.tokens,
    required this.cellKey,
  });

  final int no;
  final bool scratched;
  final J18Tokens tokens;
  final Key cellKey;

  @override
  Widget build(BuildContext context) {
    return Center(
      key: cellKey,
      child: Text(
        '$no',
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 11,
          color: scratched ? tokens.muted : tokens.text,
          decoration: scratched ? TextDecoration.lineThrough : null,
        ),
      ),
    );
  }
}

class _IndexLabel extends StatelessWidget {
  const _IndexLabel({
    required this.no,
    required this.scratched,
    required this.tokens,
  });

  final int no;
  final bool scratched;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 9,
      height: 1.05,
      color: scratched ? tokens.muted : tokens.text,
      decoration: scratched ? TextDecoration.lineThrough : null,
    );
    return Column(
      key: Key('qin-row-$no'),
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text('指數', style: style),
        Text('$no', style: style),
      ],
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({
    required this.place,
    required this.mode,
    required this.tokens,
    required this.onMode,
  });

  final bool place;
  final QinMode mode;
  final J18Tokens tokens;
  final ValueChanged<QinMode> onMode;

  @override
  Widget build(BuildContext context) {
    final odds = place ? '連贏位置賠率' : '連贏賠率';
    final index = place ? '連贏位置指數' : '連贏指數';
    final style = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 11,
      color: tokens.muted,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('上三角　$odds　大熱　降20%　降50%', style: style),
        const SizedBox(height: 2),
        Text('下三角　$index　85–86　87–88　89+', style: style),
        const SizedBox(height: 6),
        Align(
          alignment: Alignment.centerRight,
          child: SizedBox(
            width: 132,
            height: 32,
            child: _ModeSwitch(
              mode: mode,
              tokens: tokens,
              onMode: onMode,
              keyed: true,
            ),
          ),
        ),
      ],
    );
  }
}
