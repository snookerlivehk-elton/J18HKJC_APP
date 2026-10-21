import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet.dart';
import 'package:j18pro_racecard/features/horse_sheet/horse_detail.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';

/// Web `horseSheet`. Silk images stay a colour block until the API phase.
class HorseSheet extends ConsumerWidget {
  const HorseSheet({required this.horseNo, super.key});

  final int horseNo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final state = ref.watch(racecardControllerProvider).asData?.value;
    final race = state?.currentRace;
    Runner? runner;
    if (race != null) {
      for (final item in race.runners) {
        if (item.no == horseNo) {
          runner = item;
          break;
        }
      }
    }
    final height = MediaQuery.sizeOf(context).height * 0.86;
    return SafeArea(
      child: SizedBox(
        key: const Key('horse-sheet'),
        height: height,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: runner == null || race == null
              ? const Align(
                  alignment: Alignment.topLeft,
                  child: Text(
                    '暫無此馬',
                    style: TextStyle(fontFamily: 'Noto Sans TC', fontSize: 16),
                  ),
                )
              : _HorseBody(race: race, runner: runner, tokens: tokens),
        ),
      ),
    );
  }
}

class _HorseBody extends ConsumerWidget {
  const _HorseBody({
    required this.race,
    required this.runner,
    required this.tokens,
  });

  final Race race;
  final Runner runner;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final split = splitJockey(runner.jockey);
    final subtitle = runner.scratched
        ? '第${race.num}場 ${race.name} · 已退出'
        : '第${race.num}場 ${race.name}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Container(
              width: 36,
              height: 28,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: runner.scratched ? tokens.muted : tokens.nav,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                '${runner.no}',
                style: const TextStyle(
                  fontFamily: 'Noto Sans TC',
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    runner.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontFamily: 'Noto Sans TC',
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: tokens.text,
                      decoration: runner.scratched
                          ? TextDecoration.lineThrough
                          : TextDecoration.none,
                    ),
                  ),
                  Text(
                    subtitle,
                    maxLines: 2,
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
            TextButton(
              key: const Key('open-water'),
              onPressed: () {
                ref
                    .read(boardSheetProvider.notifier)
                    .open(const BoardSheetRequest.water());
              },
              child: const Text(
                '水位',
                style: TextStyle(fontFamily: 'Noto Sans TC'),
              ),
            ),
            IconButton(
              key: const Key('horse-close'),
              tooltip: '關閉',
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            _OddsBox(label: '檔位', value: '${runner.draw}', tokens: tokens),
            _OddsBox(
              label: '獨贏',
              value: horseWinText(runner),
              valueKey: const Key('horse-win'),
              tokens: tokens,
            ),
            _OddsBox(
              label: '位置',
              value: horsePlaceText(runner),
              valueKey: const Key('horse-place'),
              tokens: tokens,
            ),
          ],
        ),
        const SizedBox(height: 8),
        Expanded(
          child: SingleChildScrollView(
            child: Column(
              children: [
                _Item('近績', sheetText(runner.form6), tokens),
                _Item('往績', sheetText(runner.recent), tokens),
                _Item(
                  '騎師',
                  split.name.isEmpty && split.delta.isEmpty
                      ? '—'
                      : jockeyLine(runner),
                  tokens,
                ),
                _Item('練馬師', sheetText(runner.trainer), tokens),
                _Item('年齡', sheetText(runner.age), tokens),
                _Item(
                  '評分',
                  withDelta(runner.rating, fmtDelta(runner.rtgDelta)),
                  tokens,
                ),
                _Item('負磅', withDelta(runner.hw, hwDeltaOf(runner)), tokens),
                _Item('排位體重', sheetText(runner.bodyWt), tokens),
                _Item('配備', sheetText(runner.gear), tokens),
                _Item('出道至今', formatCareer(runner.career), tokens),
                _Item('跑道', sheetText(runner.rail), tokens),
                _Item('父系', sheetText(runner.sire), tokens),
                _Item('母系', sheetText(runner.dam), tokens),
                _Item('外祖父', sheetText(runner.damsire), tokens),
                _Item('馬主', sheetText(runner.owner), tokens),
                _Item('獎金', sheetText(runner.prize), tokens),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _OddsBox extends StatelessWidget {
  const _OddsBox({
    required this.label,
    required this.value,
    required this.tokens,
    this.valueKey,
  });

  final String label;
  final String value;
  final J18Tokens tokens;
  final Key? valueKey;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 3),
        padding: const EdgeInsets.symmetric(vertical: 8),
        decoration: BoxDecoration(
          color: tokens.shell,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: tokens.line),
        ),
        child: Column(
          children: [
            Text(
              label,
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 12,
                color: tokens.muted,
              ),
            ),
            Text(
              value,
              key: valueKey,
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: tokens.text,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Item extends StatelessWidget {
  const _Item(this.label, this.value, this.tokens);

  final String label;
  final String value;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final muted = value == '—';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 13,
                color: tokens.muted,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 14,
                color: muted ? tokens.muted : tokens.text,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
