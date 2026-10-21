import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/famous_tips/famous_tips.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record_sheet.dart';

/// Web famous-tips sheet. The date is the global meeting.
///
/// Race pills only change this sheet. They do not call [RacecardController.selectRace].
/// This is not the tip-record「心水名家榜」.
class FamousTipsSheet extends ConsumerStatefulWidget {
  const FamousTipsSheet({super.key});

  @override
  ConsumerState<FamousTipsSheet> createState() => _FamousTipsSheetState();
}

class _FamousTipsSheetState extends ConsumerState<FamousTipsSheet> {
  int? _pinnedRaceNum;

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final state = ref.watch(racecardControllerProvider).asData?.value;
    final meeting = state?.meeting;
    final currentRaceNum = state?.currentRaceNum ?? 0;
    final visibleNum = famousVisibleRaceNum(
      meeting,
      currentRaceNum,
      pinnedRaceNum: _pinnedRaceNum,
    );
    final race = meeting?.raceByNum(visibleNum);
    final maxHeight = MediaQuery.sizeOf(context).height * 0.9;
    return TipSheetScroll(
      key: const Key('sheet-famous'),
      maxHeight: maxHeight,
      header: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
          child: _TitleBar(title: famousTipsTitle(meeting), tokens: tokens),
        ),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _RacePills(
                races: meeting?.races ?? const <Race>[],
                selectedNum: visibleNum,
                tokens: tokens,
                onSelect: (raceNum) => setState(() => _pinnedRaceNum = raceNum),
              ),
              const SizedBox(height: 8),
              _FinishLine(
                race: race,
                currentRaceNum: currentRaceNum,
                tokens: tokens,
              ),
              const SizedBox(height: 12),
              _Aggregate(
                race: race,
                currentRaceNum: currentRaceNum,
                tokens: tokens,
              ),
              for (final group in famousGroups) ...[
                const SizedBox(height: 14),
                _GroupSection(
                  group: group,
                  race: race,
                  currentRaceNum: currentRaceNum,
                  tokens: tokens,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _TitleBar extends StatelessWidget {
  const _TitleBar({required this.title, required this.tokens});

  final String title;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            key: const Key('famous-title'),
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: tokens.text,
            ),
          ),
        ),
        Semantics(
          button: true,
          label: '關閉',
          child: ExcludeSemantics(
            child: IconButton(
              key: const Key('famous-close'),
              tooltip: '關閉',
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close),
            ),
          ),
        ),
      ],
    );
  }
}

class _RacePills extends StatelessWidget {
  const _RacePills({
    required this.races,
    required this.selectedNum,
    required this.tokens,
    required this.onSelect,
  });

  final List<Race> races;
  final int selectedNum;
  final J18Tokens tokens;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    if (races.isEmpty) {
      return Text(
        '暫無場次',
        key: const Key('famous-no-races'),
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 14,
          color: tokens.muted,
        ),
      );
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final race in races)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: _RacePill(
                raceNum: race.num,
                selected: race.num == selectedNum,
                tokens: tokens,
                onSelect: () => onSelect(race.num),
              ),
            ),
        ],
      ),
    );
  }
}

class _RacePill extends StatelessWidget {
  const _RacePill({
    required this.raceNum,
    required this.selected,
    required this.tokens,
    required this.onSelect,
  });

  final int raceNum;
  final bool selected;
  final J18Tokens tokens;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      key: Key('famous-race-$raceNum'),
      style: TextButton.styleFrom(
        foregroundColor: Colors.white,
        backgroundColor: selected ? tokens.blue : tokens.green,
        minimumSize: const Size(32, 26),
        padding: const EdgeInsets.symmetric(horizontal: 8),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        visualDensity: VisualDensity.compact,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      ),
      onPressed: onSelect,
      child: Text(
        '$raceNum',
        style: const TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 13,
          fontWeight: FontWeight.w800,
          height: 1,
        ),
      ),
    );
  }
}

class _FinishLine extends StatelessWidget {
  const _FinishLine({
    required this.race,
    required this.currentRaceNum,
    required this.tokens,
  });

  final Race? race;
  final int currentRaceNum;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final settled =
        race != null &&
        famousRaceSettled(race!, currentRaceNum: currentRaceNum);
    final labelStyle = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 14,
      fontWeight: FontWeight.w700,
      color: tokens.text,
    );
    final muted = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 14,
      color: tokens.muted,
    );
    if (!settled) {
      return Row(
        key: const Key('famous-finish'),
        children: [
          Text('賽果', style: labelStyle),
          const SizedBox(width: 8),
          Text('尚未派彩', style: muted),
        ],
      );
    }
    final finish = famousFinishTop(race!);
    return Row(
      key: const Key('famous-finish'),
      children: [
        Text('冠亞季殿', style: labelStyle),
        const SizedBox(width: 8),
        if (finish.isEmpty)
          Text('暫無名次', style: muted)
        else
          for (final no in finish)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: NumberCircle(
                text: '$no',
                kind: famousCircleKind(
                  race!,
                  no,
                  currentRaceNum: currentRaceNum,
                ),
              ),
            ),
      ],
    );
  }
}

class _Aggregate extends StatelessWidget {
  const _Aggregate({
    required this.race,
    required this.currentRaceNum,
    required this.tokens,
  });

  final Race? race;
  final int currentRaceNum;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final picks = famousAggregateTips(race);
    return Column(
      key: const Key('famous-agg'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '綜合心水',
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: tokens.text,
          ),
        ),
        Text(
          '全名家加權 · 最多 6 個',
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 12,
            color: tokens.muted,
          ),
        ),
        const SizedBox(height: 6),
        if (race == null || picks.isEmpty)
          Text(
            '暫無貼士',
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 14,
              color: tokens.muted,
            ),
          )
        else
          _NumberWrap(
            race: race!,
            numbers: picks,
            currentRaceNum: currentRaceNum,
          ),
        const SizedBox(height: 4),
        Text(
          '按「最多人看好」優先，同分再看提供時間早晚與心水順位。',
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 12,
            height: 1.35,
            color: tokens.muted,
          ),
        ),
      ],
    );
  }
}

class _GroupSection extends StatelessWidget {
  const _GroupSection({
    required this.group,
    required this.race,
    required this.currentRaceNum,
    required this.tokens,
  });

  final FamousGroup group;
  final Race? race;
  final int currentRaceNum;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final list = [
      for (final tipster in famousTipsters)
        if (tipster.group == group.key) tipster,
    ];
    return Column(
      key: Key('famous-group-${group.key}'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          group.name,
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: tokens.text,
          ),
        ),
        Text(
          group.hint,
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 12,
            color: tokens.muted,
          ),
        ),
        const SizedBox(height: 6),
        if (list.isEmpty)
          Text(
            '此區暫無名家',
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 14,
              color: tokens.muted,
            ),
          )
        else
          for (final tipster in list)
            _TipsterRow(
              tipster: tipster,
              race: race,
              currentRaceNum: currentRaceNum,
              tokens: tokens,
            ),
      ],
    );
  }
}

class _TipsterRow extends StatelessWidget {
  const _TipsterRow({
    required this.tipster,
    required this.race,
    required this.currentRaceNum,
    required this.tokens,
  });

  final FamousTipster tipster;
  final Race? race;
  final int currentRaceNum;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final picks = famousTipsForTipster(tipster, race);
    final muted = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 13,
      color: tokens.muted,
    );
    return Padding(
      key: Key('famous-tipster-${tipster.id}'),
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  tipster.name,
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 15,
                    color: tokens.text,
                  ),
                ),
              ),
              Text(
                tipFmtRate(tipster.wins, tipster.plays),
                key: Key('famous-rate-${tipster.id}'),
                style: muted,
              ),
              Text('（${tipster.wins}/${tipster.plays}場）', style: muted),
            ],
          ),
          const SizedBox(height: 4),
          if (picks.isEmpty)
            Text('暫無貼士', style: muted)
          else
            _NumberWrap(
              race: race!,
              numbers: picks,
              currentRaceNum: currentRaceNum,
            ),
        ],
      ),
    );
  }
}

class _NumberWrap extends StatelessWidget {
  const _NumberWrap({
    required this.race,
    required this.numbers,
    required this.currentRaceNum,
  });

  final Race race;
  final List<int> numbers;
  final int currentRaceNum;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final no in numbers)
          NumberCircle(
            text: '$no',
            kind: famousCircleKind(race, no, currentRaceNum: currentRaceNum),
          ),
      ],
    );
  }
}
