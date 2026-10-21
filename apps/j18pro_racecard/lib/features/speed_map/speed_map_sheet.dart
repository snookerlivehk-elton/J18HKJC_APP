import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:j18pro_racecard/app/app_theme.dart';
import 'package:j18pro_racecard/features/speed_map/speed_map.dart';
import 'package:j18pro_racecard/features/speed_map/speed_map_repository.dart';

/// Web `speedMapOverlay`. One board sheet; opening it replaces any other.
///
/// A failed fetch stays inside this sheet. It does not replace the racecard.
class SpeedMapSheet extends ConsumerStatefulWidget {
  const SpeedMapSheet({required this.raceNum, super.key});

  final int raceNum;

  @override
  ConsumerState<SpeedMapSheet> createState() => _SpeedMapSheetState();
}

class _SpeedMapSheetState extends ConsumerState<SpeedMapSheet> {
  var _token = 0;
  var _loading = true;
  SpeedMapChart? _chart;
  SpeedMapFailure? _failure;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final token = ++_token;
    final raceNum = widget.raceNum;
    try {
      final chart = await ref.read(speedMapRepositoryProvider).load(raceNum);
      if (!mounted || token != _token) return;
      setState(() {
        _chart = chart;
        _failure = null;
        _loading = false;
      });
    } on SpeedMapException catch (error) {
      if (!mounted || token != _token) return;
      setState(() {
        _chart = null;
        _failure = error.kind;
        _loading = false;
      });
    } catch (_) {
      if (!mounted || token != _token) return;
      setState(() {
        _chart = null;
        _failure = SpeedMapFailure.offline;
        _loading = false;
      });
    }
  }

  String get _meta {
    if (_loading) return '第${widget.raceNum}場 · 載入走位圖…';
    final chart = _chart;
    if (chart != null) return chart.metaFor(widget.raceNum);
    return '第${widget.raceNum}場';
  }

  @override
  Widget build(BuildContext context) {
    final tokens = Theme.of(context).extension<J18Tokens>() ?? J18Tokens.light;
    final height = MediaQuery.sizeOf(context).height * 0.86;
    return SafeArea(
      child: SizedBox(
        key: const Key('sheet-speed-map'),
        height: height,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 4, 0),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '速勢走位圖',
                      key: const Key('speed-title'),
                      style: TextStyle(
                        fontFamily: 'Noto Sans TC',
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: tokens.text,
                      ),
                    ),
                  ),
                  IconButton(
                    key: const Key('speed-close'),
                    tooltip: '關閉',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text(
                _meta,
                key: const Key('speed-meta'),
                style: TextStyle(
                  fontFamily: 'Noto Sans TC',
                  fontSize: 13,
                  color: tokens.muted,
                ),
              ),
            ),
            Expanded(
              child: Semantics(
                container: true,
                explicitChildNodes: true,
                label: '全場馬匹跑位圖',
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: _body(tokens),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body(J18Tokens tokens) {
    if (_loading) {
      return Text(
        '正在載入全場跑位圖…',
        key: const Key('speed-loading'),
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 14,
          color: tokens.muted,
        ),
      );
    }
    final failure = _failure;
    if (failure != null) {
      return Text(
        failure == SpeedMapFailure.noChart ? '此場暫無走位圖' : '暫未能載入走位圖，請稍後再試',
        key: const Key('speed-error'),
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 14,
          color: tokens.text,
        ),
      );
    }
    final chart = _chart;
    if (chart == null) {
      return Text(
        '此場暫無走位圖',
        key: const Key('speed-error'),
        style: TextStyle(
          fontFamily: 'Noto Sans TC',
          fontSize: 14,
          color: tokens.text,
        ),
      );
    }
    return Image.memory(
      chart.bytes,
      key: const Key('speed-image'),
      semanticLabel: '第${widget.raceNum}場速勢走位圖',
      fit: BoxFit.fitWidth,
      gaplessPlayback: true,
      errorBuilder: (context, error, stackTrace) {
        return Text(
          '此場暫無走位圖',
          key: const Key('speed-error'),
          style: TextStyle(
            fontFamily: 'Noto Sans TC',
            fontSize: 14,
            color: tokens.text,
          ),
        );
      },
    );
  }
}
