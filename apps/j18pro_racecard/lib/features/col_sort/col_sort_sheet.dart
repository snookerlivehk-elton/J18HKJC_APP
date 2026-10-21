import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/features/col_sort/col_layout.dart';
import 'package:j18pro_racecard/features/racecard_table/scroll_columns.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record_sheet.dart';

/// Web `colSortOverlay`. Picking a field, then the arrows, writes the table.
class ColSortSheet extends ConsumerStatefulWidget {
  const ColSortSheet({super.key});

  @override
  ConsumerState<ColSortSheet> createState() => _ColSortSheetState();
}

class _ColSortSheetState extends ConsumerState<ColSortSheet> {
  String? _side;
  String? _key;

  void _select(String side, String id) {
    setState(() {
      if (_side == side && _key == id) {
        _side = null;
        _key = null;
      } else {
        _side = side;
        _key = id;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final layout = ref.watch(colLayoutProvider);
    final notifier = ref.read(colLayoutProvider.notifier);
    final visibleIndex = _side == 'vis'
        ? layout.visible.indexOf(_key ?? '')
        : -1;
    final hiddenIndex = _side == 'hid' ? layout.hidden.indexOf(_key ?? '') : -1;
    final maxHeight = MediaQuery.sizeOf(context).height * 0.9;
    return TipSheetScroll(
      key: const Key('sheet-col-sort'),
      maxHeight: maxHeight,
      header: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '馬匹數據排序',
                  key: const Key('col-sort-title'),
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: tokens.text,
                  ),
                ),
              ),
              IconButton(
                key: const Key('col-sort-close'),
                tooltip: '關閉',
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
        ),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: _Pane(
                      title: '未顯示',
                      side: 'hid',
                      ids: layout.hidden,
                      selectedSide: _side,
                      selectedKey: _key,
                      tokens: tokens,
                      onSelect: _select,
                    ),
                  ),
                  Column(
                    children: [
                      _Arrow(
                        buttonKey: const Key('col-sort-up'),
                        tooltip: '上移',
                        icon: Icons.arrow_upward,
                        onPressed: visibleIndex > 0
                            ? () => notifier.moveVisible(_key!, -1)
                            : null,
                      ),
                      Row(
                        children: [
                          _Arrow(
                            buttonKey: const Key('col-sort-left'),
                            tooltip: '移至未顯示',
                            icon: Icons.arrow_back,
                            onPressed: visibleIndex >= 0
                                ? () {
                                    final id = _key!;
                                    notifier.moveToHidden(id);
                                    setState(() => _side = 'hid');
                                  }
                                : null,
                          ),
                          _Arrow(
                            buttonKey: const Key('col-sort-right'),
                            tooltip: '移至已顯示',
                            icon: Icons.arrow_forward,
                            onPressed: hiddenIndex >= 0
                                ? () {
                                    final id = _key!;
                                    notifier.moveToVisible(id);
                                    setState(() => _side = 'vis');
                                  }
                                : null,
                          ),
                        ],
                      ),
                      _Arrow(
                        buttonKey: const Key('col-sort-down'),
                        tooltip: '下移',
                        icon: Icons.arrow_downward,
                        onPressed:
                            visibleIndex >= 0 &&
                                visibleIndex < layout.visible.length - 1
                            ? () => notifier.moveVisible(_key!, 1)
                            : null,
                      ),
                    ],
                  ),
                  Expanded(
                    child: _Pane(
                      title: '已顯示',
                      side: 'vis',
                      ids: layout.visible,
                      selectedSide: _side,
                      selectedKey: _key,
                      tokens: tokens,
                      onSelect: _select,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  key: const Key('col-sort-reset'),
                  onPressed: () {
                    notifier.reset();
                    setState(() {
                      _side = null;
                      _key = null;
                    });
                  },
                  child: const Text(
                    '復位',
                    style: TextStyle(fontFamily: 'Noto Sans TC'),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Arrow extends StatelessWidget {
  const _Arrow({
    required this.buttonKey,
    required this.tooltip,
    required this.icon,
    required this.onPressed,
  });

  final Key buttonKey;
  final String tooltip;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      key: buttonKey,
      tooltip: tooltip,
      onPressed: onPressed,
      visualDensity: VisualDensity.compact,
      icon: Icon(icon),
    );
  }
}

class _Pane extends StatelessWidget {
  const _Pane({
    required this.title,
    required this.side,
    required this.ids,
    required this.selectedSide,
    required this.selectedKey,
    required this.tokens,
    required this.onSelect,
  });

  final String title;
  final String side;
  final List<String> ids;
  final String? selectedSide;
  final String? selectedKey;
  final J18Tokens tokens;
  final void Function(String side, String id) onSelect;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          title,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 14,
            fontWeight: FontWeight.w700,
            color: tokens.text,
          ),
        ),
        const SizedBox(height: 6),
        if (ids.isEmpty)
          Text(
            '（空）',
            key: Key('col-empty-$side'),
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 13,
              color: tokens.muted,
            ),
          )
        else
          for (final id in ids)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: _Item(
                id: id,
                side: side,
                selected: selectedSide == side && selectedKey == id,
                tokens: tokens,
                onSelect: () => onSelect(side, id),
              ),
            ),
      ],
    );
  }
}

class _Item extends StatelessWidget {
  const _Item({
    required this.id,
    required this.side,
    required this.selected,
    required this.tokens,
    required this.onSelect,
  });

  final String id;
  final String side;
  final bool selected;
  final J18Tokens tokens;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      key: Key('col-$side-$id'),
      style: TextButton.styleFrom(
        foregroundColor: selected ? Colors.white : tokens.text,
        backgroundColor: selected ? tokens.nav : tokens.page,
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        minimumSize: const Size(0, 32),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        visualDensity: VisualDensity.compact,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(6),
          side: BorderSide(color: selected ? tokens.nav : tokens.line),
        ),
      ),
      onPressed: onSelect,
      child: Text(
        scrollColumnById(id)?.header ?? id,
        style: const TextStyle(fontFamily: 'Noto Sans TC', fontSize: 13),
      ),
    );
  }
}
