import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// One primary board sheet. Opening any kind replaces the one already open
/// (`closeAllBoardOverlays` then show the next).
enum BoardSheetKind {
  menu,
  calendar,
  tipRecord,
  famous,
  colSort,
  payout,
  horse,
  water,
  synthReview,
  jtCollab,
  speedMap,
}

@immutable
class BoardSheetRequest {
  const BoardSheetRequest._(this.kind, {this.horseNo, this.raceNum});

  const BoardSheetRequest.menu() : this._(BoardSheetKind.menu);

  const BoardSheetRequest.calendar() : this._(BoardSheetKind.calendar);

  const BoardSheetRequest.tipRecord() : this._(BoardSheetKind.tipRecord);

  const BoardSheetRequest.famous() : this._(BoardSheetKind.famous);

  const BoardSheetRequest.colSort() : this._(BoardSheetKind.colSort);

  const BoardSheetRequest.payout(int raceNum)
    : this._(BoardSheetKind.payout, raceNum: raceNum);

  const BoardSheetRequest.horse(int horseNo)
    : this._(BoardSheetKind.horse, horseNo: horseNo);

  const BoardSheetRequest.water() : this._(BoardSheetKind.water);

  const BoardSheetRequest.synthReview(int horseNo)
    : this._(BoardSheetKind.synthReview, horseNo: horseNo);

  const BoardSheetRequest.jtCollab(int horseNo)
    : this._(BoardSheetKind.jtCollab, horseNo: horseNo);

  const BoardSheetRequest.speedMap(int raceNum)
    : this._(BoardSheetKind.speedMap, raceNum: raceNum);

  final BoardSheetKind kind;
  final int? horseNo;
  final int? raceNum;

  @override
  bool operator ==(Object other) {
    return other is BoardSheetRequest &&
        kind == other.kind &&
        horseNo == other.horseNo &&
        raceNum == other.raceNum;
  }

  @override
  int get hashCode => Object.hash(kind, horseNo, raceNum);
}

final boardSheetProvider =
    NotifierProvider<BoardSheetController, BoardSheetRequest?>(
      BoardSheetController.new,
    );

class BoardSheetController extends Notifier<BoardSheetRequest?> {
  @override
  BoardSheetRequest? build() => null;

  /// Closes whatever sheet is up, then shows [next].
  void open(BoardSheetRequest next) {
    state = next;
  }

  void close() {
    state = null;
  }
}
