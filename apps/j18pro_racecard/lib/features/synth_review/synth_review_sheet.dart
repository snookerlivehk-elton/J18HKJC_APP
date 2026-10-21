import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/racecard/racecard_controller.dart';
import 'package:j18pro_racecard/features/synth_review/horse_notes_controller.dart';
import 'package:j18pro_racecard/features/synth_review/synth_review.dart';
import 'package:j18pro_racecard/features/tip_record/tip_record_sheet.dart';

enum _NoteSide { write, hist }

/// Web `synthReviewOverlay`. One board sheet; opening it replaces the horse
/// sheet. Close, system back, and the scrim all save a dirty draft first.
class SynthReviewSheet extends ConsumerStatefulWidget {
  const SynthReviewSheet({required this.horseNo, super.key});

  final int horseNo;

  @override
  ConsumerState<SynthReviewSheet> createState() => _SynthReviewSheetState();
}

class _SynthReviewSheetState extends ConsumerState<SynthReviewSheet> {
  final _input = TextEditingController();
  var _side = _NoteSide.write;
  var _baseline = '';
  String? _expandedId;
  var _allowPop = false;
  var _closing = false;

  @override
  void initState() {
    super.initState();
    final draft = _recordOf(ref.read(horseNotesProvider)).openingDraft;
    _baseline = draft;
    _input.text = draft;
  }

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  bool get _dirty => _input.text != _baseline;

  HorseNoteRecord _recordOf(Map<String, HorseNoteRecord> saved) {
    final view = ref.read(racecardControllerProvider).asData?.value;
    final race = view?.currentRace;
    final runner = _runnerOf(race);
    return resolveHorseNote(
      saved: saved,
      date: view?.meeting.date ?? '',
      raceNum: race?.num ?? 0,
      horseNo: widget.horseNo,
      scratched: runner?.scratched ?? false,
    );
  }

  Runner? _runnerOf(Race? race) {
    if (race == null) return null;
    for (final item in race.runners) {
      if (item.no == widget.horseNo) return item;
    }
    return null;
  }

  Future<void> _persist({bool updateField = true}) async {
    final view = ref.read(racecardControllerProvider).asData?.value;
    final race = view?.currentRace;
    final runner = _runnerOf(race);
    if (view == null || race == null || runner == null) return;
    final ok = await ref
        .read(horseNotesProvider.notifier)
        .save(
          date: view.meeting.date,
          raceNum: race.num,
          runner: runner,
          raceMeta: race.meta,
          courseLabel: view.meeting.courseLabel,
          draft: _input.text,
        );
    if (!ok || !mounted || !updateField) return;
    final trimmed = _input.text.trim();
    setState(() {
      _baseline = trimmed;
      _input.value = TextEditingValue(
        text: trimmed,
        selection: TextSelection.collapsed(offset: trimmed.length),
      );
    });
  }

  Future<void> _setSide(_NoteSide next) async {
    if (_side == next) return;
    if (next == _NoteSide.hist && _dirty) {
      await _persist();
    }
    if (!mounted) return;
    setState(() {
      _side = next;
      if (next == _NoteSide.write) _expandedId = null;
    });
  }

  Future<void> _requestClose() async {
    if (_closing) return;
    _closing = true;
    if (_dirty) await _persist(updateField: false);
    if (!mounted) return;
    setState(() => _allowPop = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop();
    });
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final saved = ref.watch(horseNotesProvider);
    final view = ref.watch(racecardControllerProvider).asData?.value;
    final race = view?.currentRace;
    final runner = _runnerOf(race);
    final record = resolveHorseNote(
      saved: saved,
      date: view?.meeting.date ?? '',
      raceNum: race?.num ?? 0,
      horseNo: widget.horseNo,
      scratched: runner?.scratched ?? false,
    );
    final review = runner == null || race == null
        ? ''
        : synthReviewText(
            runner: runner,
            raceNum: race.num,
            meetingDate: view?.meeting.date ?? '',
          );
    final title = runner == null
        ? '綜合評述'
        : '綜合評述 · ${runner.no}${runner.name.isEmpty ? '' : ' ${runner.name}'}';
    final maxHeight = MediaQuery.sizeOf(context).height * 0.9;
    return PopScope(
      canPop: _allowPop,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop || _closing) return;
        _requestClose();
      },
      child: TipSheetScroll(
        key: const Key('sheet-synth-review'),
        maxHeight: maxHeight,
        header: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 4, 0),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    key: const Key('synth-title'),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
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
                      key: const Key('synth-close'),
                      tooltip: '關閉',
                      onPressed: _requestClose,
                      icon: const Icon(Icons.close),
                    ),
                  ),
                ),
              ],
            ),
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
                Text(
                  review,
                  key: const Key('synth-review-body'),
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 14,
                    height: 1.45,
                    color: tokens.text,
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: _SideButton(
                        buttonKey: const Key('synth-note-write'),
                        label: '為該馬匹創建個人筆記',
                        selected: _side == _NoteSide.write,
                        tokens: tokens,
                        onPressed: () => _setSide(_NoteSide.write),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: _SideButton(
                        buttonKey: const Key('synth-note-hist'),
                        label: '點擊查看歷史筆記（${record.history.length}條）',
                        labelKey: const Key('synth-note-count'),
                        selected: _side == _NoteSide.hist,
                        tokens: tokens,
                        onPressed: () => _setSide(_NoteSide.hist),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                if (_side == _NoteSide.write)
                  _WritePanel(
                    input: _input,
                    enabled: runner != null && !runner.scratched,
                    tokens: tokens,
                    onSave: () => _persist(),
                  )
                else
                  _HistPanel(
                    record: record,
                    expandedId: _expandedId,
                    tokens: tokens,
                    onToggle: (id) {
                      setState(() {
                        _expandedId = _expandedId == id ? null : id;
                      });
                    },
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SideButton extends StatelessWidget {
  const _SideButton({
    required this.buttonKey,
    required this.label,
    required this.selected,
    required this.tokens,
    required this.onPressed,
    this.labelKey,
  });

  final Key buttonKey;
  final Key? labelKey;
  final String label;
  final bool selected;
  final J18Tokens tokens;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      key: buttonKey,
      style: TextButton.styleFrom(
        backgroundColor: selected ? tokens.nav : tokens.shell,
        foregroundColor: selected ? Colors.white : tokens.text,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
        minimumSize: const Size(0, 40),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      onPressed: onPressed,
      child: Text(
        label,
        key: labelKey,
        maxLines: 2,
        textAlign: TextAlign.center,
        style: const TextStyle(fontFamily: 'Noto Sans TC', fontSize: 13),
      ),
    );
  }
}

class _WritePanel extends StatelessWidget {
  const _WritePanel({
    required this.input,
    required this.enabled,
    required this.tokens,
    required this.onSave,
  });

  final TextEditingController input;
  final bool enabled;
  final J18Tokens tokens;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          key: const Key('synth-note-input'),
          controller: input,
          enabled: enabled,
          minLines: 4,
          maxLines: 6,
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 14,
            color: tokens.text,
          ),
          decoration: InputDecoration(
            hintText: '輸入本場賽馬筆記…',
            hintStyle: TextStyle(
              fontFamily: 'Noto Sans TC',
              fontSize: 14,
              color: tokens.muted,
            ),
            filled: true,
            fillColor: tokens.page,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: tokens.line),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton(
            key: const Key('synth-note-save'),
            onPressed: enabled ? onSave : null,
            style: FilledButton.styleFrom(backgroundColor: tokens.nav),
            child: const Text(
              '保存',
              style: TextStyle(fontFamily: 'Noto Sans TC'),
            ),
          ),
        ),
      ],
    );
  }
}

class _HistPanel extends StatelessWidget {
  const _HistPanel({
    required this.record,
    required this.expandedId,
    required this.tokens,
    required this.onToggle,
  });

  final HorseNoteRecord record;
  final String? expandedId;
  final J18Tokens tokens;
  final ValueChanged<String> onToggle;

  @override
  Widget build(BuildContext context) {
    if (record.history.isEmpty) {
      return Text(
        '暫無歷史筆記',
        key: const Key('synth-note-empty'),
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
        for (final entry in record.history)
          _HistRow(
            entry: entry,
            open: expandedId == entry.id,
            tokens: tokens,
            onToggle: () => onToggle(entry.id),
          ),
      ],
    );
  }
}

class _HistRow extends StatelessWidget {
  const _HistRow({
    required this.entry,
    required this.open,
    required this.tokens,
    required this.onToggle,
  });

  final HorseNoteEntry entry;
  final bool open;
  final J18Tokens tokens;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        key: Key('synth-hist-${entry.id}'),
        color: tokens.shell,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onToggle,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  horseNoteMeta(entry),
                  style: TextStyle(
                    fontFamily: 'Noto Sans TC',
                    fontSize: 12,
                    color: tokens.muted,
                  ),
                ),
                if (open) ...[
                  const SizedBox(height: 6),
                  Text(
                    entry.text,
                    style: TextStyle(
                      fontFamily: 'Noto Sans TC',
                      fontSize: 14,
                      color: tokens.text,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
