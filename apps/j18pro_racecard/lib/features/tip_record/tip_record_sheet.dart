import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record.dart';

/// Sizes to the child, and scrolls inside [maxHeight] once the child is taller.
///
/// This is the Flutter stand-in for Web `syncFillSheetHeight`: short content
/// does not stretch the sheet, long content scrolls in place.
class TipSheetScroll extends StatelessWidget {
  const TipSheetScroll({
    required this.maxHeight,
    required this.child,
    this.header,
    super.key,
  });

  final double maxHeight;

  /// Stays visible while [child] scrolls. Omitted when the whole body is short.
  final Widget? header;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ?header,
          Flexible(
            fit: FlexFit.loose,
            child: SingleChildScrollView(child: child),
          ),
        ],
      ),
    );
  }
}

/// Web tip-record sheet: 今日心水, 戰績統計, 心水名家榜.
///
/// The date is the global meeting. There is no calendar on this sheet.
/// Help and leaderboard rows start closed each time the sheet is created.
class TipRecordSheet extends ConsumerStatefulWidget {
  const TipRecordSheet({super.key});

  @override
  ConsumerState<TipRecordSheet> createState() => _TipRecordSheetState();
}

class _TipRecordSheetState extends ConsumerState<TipRecordSheet> {
  var _scope = 'day';
  var _helpOpen = false;
  final _openIds = <String>{};

  void _toggleLeader(String id) {
    setState(() {
      if (_openIds.contains(id)) {
        _openIds.remove(id);
      } else {
        _openIds.add(id);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final state = ref.watch(racecardControllerProvider).asData?.value;
    final meeting = state?.meeting;
    final currentRaceNum = state?.currentRaceNum ?? 0;
    final maxHeight = MediaQuery.sizeOf(context).height * 0.9;
    return TipSheetScroll(
      key: const Key('sheet-tip-record'),
      maxHeight: maxHeight,
      header: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
          child: _TitleBar(title: tipRecordTitle(meeting), tokens: tokens),
        ),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _SectionTitle('今日心水', tokens: tokens),
              const SizedBox(height: 6),
              _DayList(
                meeting: meeting,
                currentRaceNum: currentRaceNum,
                tokens: tokens,
              ),
              const SizedBox(height: 16),
              _StatsSection(
                meeting: meeting,
                currentRaceNum: currentRaceNum,
                scope: _scope,
                helpOpen: _helpOpen,
                tokens: tokens,
                onToggleHelp: () => setState(() => _helpOpen = !_helpOpen),
                onScope: (scope) => setState(() => _scope = scope),
              ),
              const SizedBox(height: 16),
              _SectionTitle('心水名家榜 · 獎金 Top 10', tokens: tokens),
              const SizedBox(height: 6),
              for (var i = 0; i < tipLeaderboard.length; i++)
                _LeaderRow(
                  rank: i + 1,
                  leader: tipLeaderboard[i],
                  open: _openIds.contains(tipLeaderboard[i].id),
                  tokens: tokens,
                  onTap: () => _toggleLeader(tipLeaderboard[i].id),
                ),
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
            key: const Key('tip-title'),
            style: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: tokens.text,
            ),
          ),
        ),
        IconButton(
          key: const Key('tip-close'),
          tooltip: '關閉',
          onPressed: () => Navigator.of(context).pop(),
          icon: const Icon(Icons.close),
        ),
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text, {required this.tokens});

  final String text;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: TextStyle(
        fontFamily: 'Noto Sans TC',
        fontSize: 16,
        fontWeight: FontWeight.w700,
        color: tokens.text,
      ),
    );
  }
}

class _DayList extends StatelessWidget {
  const _DayList({
    required this.meeting,
    required this.currentRaceNum,
    required this.tokens,
  });

  final Meeting? meeting;
  final int currentRaceNum;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final races = meeting?.races ?? const <Race>[];
    if (races.isEmpty) {
      return Text(
        '暫無場次',
        key: const Key('tip-day-empty'),
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 14,
          color: tokens.muted,
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final race in races)
          Padding(
            key: Key('tip-day-race-${race.num}'),
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                SizedBox(
                  width: 64,
                  child: Text(
                    '第${race.num}場',
                    style: TextStyle(
                      fontFamily: 'Noto Sans TC',
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: tokens.text,
                    ),
                  ),
                ),
                Expanded(
                  child: _PickRow(
                    race: race,
                    currentRaceNum: currentRaceNum,
                    tokens: tokens,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _PickRow extends StatelessWidget {
  const _PickRow({
    required this.race,
    required this.currentRaceNum,
    required this.tokens,
  });

  final Race race;
  final int currentRaceNum;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final picks = demoTipPicks(race);
    if (picks.isEmpty) {
      return Text(
        '未標記',
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 14,
          color: tokens.muted,
        ),
      );
    }
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final no in picks)
          NumberCircle(
            text: '$no',
            kind: tipCircleKind(race, no, currentRaceNum: currentRaceNum),
          ),
      ],
    );
  }
}

class _StatsSection extends StatelessWidget {
  const _StatsSection({
    required this.meeting,
    required this.currentRaceNum,
    required this.scope,
    required this.helpOpen,
    required this.tokens,
    required this.onToggleHelp,
    required this.onScope,
  });

  final Meeting? meeting;
  final int currentRaceNum;
  final String scope;
  final bool helpOpen;
  final J18Tokens tokens;
  final VoidCallback onToggleHelp;
  final ValueChanged<String> onScope;

  @override
  Widget build(BuildContext context) {
    final stats = meeting == null
        ? {
            for (final def in tipStatDefs)
              def.key: const TipStatLine(wins: 0, plays: 0, prize: 0),
          }
        : tipAggregateStats(
            meeting!,
            currentRaceNum: currentRaceNum,
            scope: scope,
          );
    final total = tipFmtPrize(tipTotalPrize(stats));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          children: [
            Text(
              '戰績統計',
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: tokens.text,
              ),
            ),
            TextButton(
              key: const Key('tip-help'),
              style: TextButton.styleFrom(
                foregroundColor: tokens.nav,
                visualDensity: VisualDensity.compact,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              onPressed: onToggleHelp,
              child: const Text(
                '規則',
                style: TextStyle(fontFamily: 'Noto Sans TC', fontSize: 14),
              ),
            ),
            _ScopeButton(
              label: '本日',
              buttonKey: const Key('tip-scope-day'),
              selected: scope == 'day',
              tokens: tokens,
              onPressed: () => onScope('day'),
            ),
            _ScopeButton(
              label: '本賽季',
              buttonKey: const Key('tip-scope-season'),
              selected: scope == 'season',
              tokens: tokens,
              onPressed: () => onScope('season'),
            ),
          ],
        ),
        if (helpOpen)
          Padding(
            key: const Key('tip-help-body'),
            padding: const EdgeInsets.only(top: 6, bottom: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final def in tipStatDefs)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 2),
                    child: Text(
                      '${def.name}（${def.range}）：${def.help}',
                      style: TextStyle(
                        fontFamily: 'Noto Sans TC',
                        fontSize: 12,
                        height: 1.35,
                        color: tokens.text,
                      ),
                    ),
                  ),
                Text(
                  tipRecordHelpFooter,
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 12,
                    height: 1.35,
                    color: tokens.muted,
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: 6),
        Text(
          '估算累積獎金 $total　（每注$tipRecordStake元）',
          key: const Key('tip-prize-total'),
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 13,
            color: tokens.text,
          ),
        ),
        const SizedBox(height: 4),
        for (final def in tipStatDefs)
          _StatRow(def: def, line: stats[def.key]!, tokens: tokens),
      ],
    );
  }
}

class _ScopeButton extends StatelessWidget {
  const _ScopeButton({
    required this.label,
    required this.buttonKey,
    required this.selected,
    required this.tokens,
    required this.onPressed,
  });

  final String label;
  final Key buttonKey;
  final bool selected;
  final J18Tokens tokens;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      key: buttonKey,
      style: TextButton.styleFrom(
        foregroundColor: selected ? Colors.white : tokens.text,
        backgroundColor: selected ? tokens.nav : tokens.page,
        visualDensity: VisualDensity.compact,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        minimumSize: const Size(0, 32),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(6),
          side: BorderSide(color: selected ? tokens.nav : tokens.line),
        ),
      ),
      onPressed: onPressed,
      child: Text(
        label,
        style: const TextStyle(fontFamily: 'Noto Sans TC', fontSize: 13),
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  const _StatRow({required this.def, required this.line, required this.tokens});

  final TipStatDef def;
  final TipStatLine line;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final muted = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 13,
      color: tokens.muted,
    );
    return Padding(
      key: Key('tip-stat-${def.key}'),
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 72,
            child: Text(
              def.name,
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 14,
                color: tokens.text,
              ),
            ),
          ),
          SizedBox(
            width: 64,
            child: Text(
              tipFmtRate(line.wins, line.plays),
              key: Key('tip-stat-rate-${def.key}'),
              style: muted,
            ),
          ),
          Expanded(child: Text('${line.wins}/${line.plays}場', style: muted)),
          Text(tipFmtPrize(line.prize), style: muted),
        ],
      ),
    );
  }
}

class _LeaderRow extends StatelessWidget {
  const _LeaderRow({
    required this.rank,
    required this.leader,
    required this.open,
    required this.tokens,
    required this.onTap,
  });

  final int rank;
  final TipLeader leader;
  final bool open;
  final J18Tokens tokens;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InkWell(
          key: Key('tip-lb-${leader.id}'),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(
              children: [
                SizedBox(
                  width: 28,
                  child: Text(
                    '$rank',
                    style: TextStyle(
                      fontFamily: 'Noto Sans TC',
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: tokens.muted,
                    ),
                  ),
                ),
                Expanded(
                  child: Text(
                    leader.name,
                    style: TextStyle(
                      fontFamily: 'Noto Sans TC',
                      fontSize: 15,
                      color: tokens.text,
                    ),
                  ),
                ),
                Text(
                  tipFmtPrize(leader.prize),
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: tokens.text,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (open)
          Padding(
            key: Key('tip-lb-detail-${leader.id}'),
            padding: const EdgeInsets.only(left: 28, bottom: 6),
            child: Column(
              children: [
                for (final def in tipStatDefs)
                  _LeaderDetail(
                    def: def,
                    triple: tipStatTriple(leader.stats[def.key]),
                    tokens: tokens,
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _LeaderDetail extends StatelessWidget {
  const _LeaderDetail({
    required this.def,
    required this.triple,
    required this.tokens,
  });

  final TipStatDef def;
  final ({int wins, int plays, int prize}) triple;
  final J18Tokens tokens;

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 12,
      color: tokens.muted,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Row(
        children: [
          SizedBox(width: 64, child: Text(def.name, style: style)),
          SizedBox(
            width: 56,
            child: Text(tipFmtRate(triple.wins, triple.plays), style: style),
          ),
          Expanded(
            child: Text('${triple.wins}/${triple.plays}場', style: style),
          ),
          Text(tipFmtPrize(triple.prize), style: style),
        ],
      ),
    );
  }
}
