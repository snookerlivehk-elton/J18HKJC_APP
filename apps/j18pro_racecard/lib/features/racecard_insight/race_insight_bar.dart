import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/board_sheet/board_sheet.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/racecard_insight/index_picks.dart';
import 'package:j18pro_racecard/features/racecard_insight/number_circle.dart';
import 'package:j18pro_racecard/features/racecard_insight/payout_detail.dart';
import 'package:j18pro_racecard/features/racecard_insight/race_status.dart';
import 'package:j18pro_racecard/features/racecard_insight/time_scrub.dart';

/// Status light, meta line, time scrub, and the two capsules above the table.
///
/// One capsule body is open at a time. The chevron toggles the drop and does
/// not collapse that body. Meta uses ellipsis (no marquee) and the running
/// light does not pulse, so widget tests can settle.
class RaceInsightBar extends ConsumerWidget {
  const RaceInsightBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(racecardControllerProvider).asData?.value;
    if (state == null) return const SizedBox.shrink();
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final brightness = Theme.of(context).brightness;
    final race = state.currentRace;
    final kind = resolveRaceStatus(race: race, dateIso: state.meeting.date);
    final colors = raceStatusColors(kind, brightness);
    final meta = formatRaceInfoLine(
      dateIso: state.meeting.date,
      race: race,
      courseLabel: state.meeting.courseLabel,
      weekdayLabel: state.meeting.weekday,
    );
    final notifier = ref.read(racecardControllerProvider.notifier);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 2, 8, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Semantics(
                label: '賽事狀態：${raceStatusLabel(kind)}',
                container: true,
                child: Row(
                  key: const Key('race-status'),
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      key: const Key('race-status-dot'),
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: colors.dot,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      raceStatusLabel(kind),
                      key: const Key('race-status-lab'),
                      style: TextStyle(
                        fontFamily: 'Noto Sans TC',
                        fontSize: 11,
                        height: 1.2,
                        fontWeight: FontWeight.w700,
                        color: colors.text,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  meta,
                  key: const Key('race-meta'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 12,
                    height: 1.2,
                    color: brightness == Brightness.dark
                        ? tokens.muted
                        : const Color(0xFF5B6575),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          TimeScrub(
            storedIndex: state.scrubPointIdx,
            onIndex: notifier.setScrubIndex,
          ),
          const SizedBox(height: 4),
          _CapsuleRail(state: state),
          if (state.capsuleDropOpen) ...[
            const SizedBox(height: 4),
            _CapsuleDrop(state: state),
          ],
        ],
      ),
    );
  }
}

class _CapsuleRail extends ConsumerWidget {
  const _CapsuleRail({required this.state});

  final RacecardViewState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final indexOpen = state.openCapsule == OpenCapsule.picks;
    final payoutOpen = state.openCapsule == OpenCapsule.payout;
    final index = _IndexCapsule(state: state, open: indexOpen);
    final payout = _PayoutCapsule(state: state, open: payoutOpen);
    return Row(
      children: [
        if (indexOpen) Expanded(child: index) else index,
        const SizedBox(width: 6),
        if (payoutOpen) Expanded(child: payout) else payout,
      ],
    );
  }
}

class _IndexCapsule extends ConsumerWidget {
  const _IndexCapsule({required this.state, required this.open});

  final RacecardViewState state;
  final bool open;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final brightness = Theme.of(context).brightness;
    final strategy = indexStrategyById(state.indexStrategyId);
    final picks = activeIndexPicks(
      race: state.currentRace,
      strategyId: state.indexStrategyId,
      scrubPointIdx: state.scrubPointIdx,
    );
    final finish = payoutFinishNosForRace(state.currentRace);
    final notifier = ref.read(racecardControllerProvider.notifier);
    return _Pill(
      open: open,
      background: brightness == Brightness.dark
          ? const Color(0xFF3A3224)
          : const Color(0xFFFFF4DF),
      border: const Color(0xFFF0D2A0),
      head: _CapsuleHead(
        headKey: const Key('capsule-index'),
        chevronKey: const Key('capsule-chev-index'),
        lines: strategy.lines,
        dropOpen: open && state.capsuleDropOpen,
        gradient: const [Color(0xFFFF9A4A), Color(0xFFE85A6A)],
        onTap: () {
          if (open) {
            notifier.toggleCapsuleDrop();
          } else {
            notifier.selectCapsule(OpenCapsule.picks);
          }
        },
      ),
      body: open
          ? _CircleStrip(
              circles: [
                for (var i = 0; i < defaultIndexPickLimit; i++)
                  if (i < picks.length)
                    NumberCircle(
                      key: Key('index-cap-$i'),
                      text: '${picks[i]}',
                      kind: kindForPick(picks[i], finish),
                    )
                  else
                    NumberCircle(
                      key: Key('index-cap-$i'),
                      text: '—',
                      kind: CircleKind.empty,
                    ),
              ],
            )
          : null,
    );
  }
}

class _PayoutCapsule extends ConsumerWidget {
  const _PayoutCapsule({required this.state, required this.open});

  final RacecardViewState state;
  final bool open;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final brightness = Theme.of(context).brightness;
    final race = state.currentRace;
    final paid = raceHasPayout(race);
    final finish = payoutFinishNosForRace(race);
    final notifier = ref.read(racecardControllerProvider.notifier);
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    return _Pill(
      open: open,
      background: brightness == Brightness.dark
          ? const Color(0xFF243040)
          : const Color(0xFFE7EEF6),
      border: brightness == Brightness.dark
          ? tokens.line
          : const Color(0xFFCFD7E4),
      head: _CapsuleHead(
        headKey: const Key('capsule-payout'),
        chevronKey: const Key('capsule-chev-payout'),
        lines: const ['賽果', '派彩'],
        dropOpen: open && state.capsuleDropOpen,
        gradient: [tokens.navTop, tokens.nav2],
        onTap: () {
          if (open) {
            notifier.toggleCapsuleDrop();
          } else {
            notifier.selectCapsule(OpenCapsule.payout);
          }
        },
      ),
      body: open
          ? _CircleStrip(
              circles: finish.isEmpty
                  ? const [
                      NumberCircle(
                        key: Key('payout-cap-0'),
                        text: '—',
                        kind: CircleKind.empty,
                      ),
                    ]
                  : [
                      for (var i = 0; i < finish.length; i++)
                        NumberCircle(
                          key: Key('payout-cap-$i'),
                          text: '${finish[i]}',
                          kind: finishKindAt(i),
                        ),
                    ],
            )
          : null,
      trailing: open
          ? Padding(
              padding: const EdgeInsets.only(right: 4),
              child: TextButton(
                key: const Key('capsule-payout-status'),
                style: TextButton.styleFrom(
                  backgroundColor: paid
                      ? (brightness == Brightness.dark
                            ? const Color(0xFFE39A45)
                            : const Color(0xFFE88B2A))
                      : const Color(0xFF3D5A80),
                  foregroundColor: Colors.white,
                  minimumSize: const Size(0, 24),
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  textStyle: const TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                onPressed: () {
                  if (!paid) return;
                  ref
                      .read(boardSheetProvider.notifier)
                      .open(BoardSheetRequest.payout(race.num));
                },
                child: Text(
                  paid ? '已派彩' : '未派彩',
                  semanticsLabel: paid ? '查看派彩詳情' : '尚未派彩',
                ),
              ),
            )
          : null,
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({
    required this.open,
    required this.background,
    required this.border,
    required this.head,
    this.body,
    this.trailing,
  });

  final bool open;
  final Color background;
  final Color border;
  final Widget head;
  final Widget? body;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 44,
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: border),
      ),
      child: Row(
        mainAxisSize: open ? MainAxisSize.max : MainAxisSize.min,
        children: [
          head,
          if (body != null)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: body,
              ),
            ),
          ?trailing,
        ],
      ),
    );
  }
}

class _CapsuleHead extends StatelessWidget {
  const _CapsuleHead({
    required this.headKey,
    required this.chevronKey,
    required this.lines,
    required this.dropOpen,
    required this.gradient,
    required this.onTap,
  });

  final Key headKey;
  final Key chevronKey;
  final List<String> lines;
  final bool dropOpen;
  final List<Color> gradient;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    const title = TextStyle(
      fontFamily: 'Noto Sans TC',
      fontSize: 10,
      height: 1.05,
      fontWeight: FontWeight.w800,
      color: Colors.white,
    );
    return Padding(
      padding: const EdgeInsets.all(4),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          key: headKey,
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Ink(
            height: 32,
            padding: const EdgeInsets.only(left: 8, right: 4),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: gradient,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(lines[0], style: title),
                    Text(lines[1], style: title),
                  ],
                ),
                const SizedBox(width: 2),
                Icon(
                  dropOpen ? Icons.expand_less : Icons.expand_more,
                  key: chevronKey,
                  size: 16,
                  color: Colors.white,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _CircleStrip extends StatelessWidget {
  const _CircleStrip({required this.circles});

  final List<Widget> circles;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (var i = 0; i < circles.length; i++) ...[
            if (i > 0) const SizedBox(width: 4),
            circles[i],
          ],
        ],
      ),
    );
  }
}

class _CapsuleDrop extends ConsumerWidget {
  const _CapsuleDrop({required this.state});

  final RacecardViewState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final brightness = Theme.of(context).brightness;
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final index = state.openCapsule == OpenCapsule.picks;
    return DecoratedBox(
      key: const Key('capsule-drop'),
      decoration: BoxDecoration(
        color: brightness == Brightness.dark
            ? const Color(0xFF1E242D)
            : Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: tokens.line),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(
          children: [
            if (index)
              for (final strategy in indexStrategies)
                _StrategyRow(
                  strategy: strategy,
                  selected: strategy.id == state.indexStrategyId,
                  race: state.currentRace,
                )
            else
              for (final race in state.meeting.races)
                _PayoutRaceRow(race: race),
          ],
        ),
      ),
    );
  }
}

class _StrategyRow extends ConsumerWidget {
  const _StrategyRow({
    required this.strategy,
    required this.selected,
    required this.race,
  });

  final IndexStrategy strategy;
  final bool selected;
  final Race race;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final picks = indexPicksForStrategy(race, strategy.id);
    final finish = payoutFinishNosForRace(race);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      child: Row(
        children: [
          SizedBox(
            width: 64,
            child: Text(
              strategy.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: tokens.text,
              ),
            ),
          ),
          Expanded(
            child: _CircleStrip(
              circles: [
                for (var i = 0; i < picks.length; i++)
                  NumberCircle(
                    text: '${picks[i]}',
                    kind: kindForPick(picks[i], finish),
                  ),
              ],
            ),
          ),
          TextButton(
            key: Key('strategy-${strategy.id}'),
            onPressed: () {
              ref
                  .read(racecardControllerProvider.notifier)
                  .setIndexStrategy(strategy.id);
            },
            style: TextButton.styleFrom(
              minimumSize: const Size(0, 28),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              padding: const EdgeInsets.symmetric(horizontal: 6),
            ),
            child: Text(
              '置頂',
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 12,
                fontWeight: selected ? FontWeight.w800 : FontWeight.w400,
                color: selected ? const Color(0xFFE88B2A) : tokens.muted,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PayoutRaceRow extends ConsumerWidget {
  const _PayoutRaceRow({required this.race});

  final Race race;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final paid = raceHasPayout(race);
    final finish = payoutFinishNosForRace(race);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      child: Row(
        children: [
          SizedBox(
            width: 48,
            child: Text(
              '第${race.num}場',
              style: TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: tokens.text,
              ),
            ),
          ),
          Expanded(
            child: _CircleStrip(
              circles: [
                for (var i = 0; i < finish.length; i++)
                  NumberCircle(text: '${finish[i]}', kind: finishKindAt(i)),
              ],
            ),
          ),
          TextButton(
            key: Key('pay-race-${race.num}'),
            onPressed: () {
              ref
                  .read(racecardControllerProvider.notifier)
                  .openPayoutForRace(race.num);
              if (paid) {
                ref
                    .read(boardSheetProvider.notifier)
                    .open(BoardSheetRequest.payout(race.num));
              }
            },
            style: TextButton.styleFrom(
              backgroundColor: paid
                  ? const Color(0xFFE88B2A)
                  : const Color(0xFF3D5A80),
              foregroundColor: Colors.white,
              minimumSize: const Size(0, 24),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              padding: const EdgeInsets.symmetric(horizontal: 8),
            ),
            child: Text(
              paid ? '已派彩' : '未派彩',
              style: const TextStyle(
                fontFamily: 'Noto Sans TC',
                fontSize: 11,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
