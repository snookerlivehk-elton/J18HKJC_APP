import 'package:flutter_test/flutter_test.dart';
import 'package:j18pro_racecard/domain/meeting.dart';
import 'package:j18pro_racecard/features/horse_sheet/horse_detail.dart';
import 'package:j18pro_racecard/features/water_sheet/water_demo.dart';

Runner _runner({
  int no = 1,
  String jockey = '何澤堯',
  bool scratched = false,
  double? win = 12,
  double? place = 4.2,
}) {
  return Runner(
    no: no,
    name: '馬$no',
    draw: 9,
    jockey: jockey,
    trainer: '羅富全',
    win: win,
    place: place,
    scratched: scratched,
    silk: null,
    form6: '6/2/2/9/2/4',
    recent: '6/2/2/9/2/4',
    age: 7,
    rating: 59,
    rtgDelta: '0',
    hw: 135,
    bodyWt: 1060,
    gear: 'TT',
    career: '2-5-1-30',
    rail: 'C',
    dam: 'La Praline',
    sire: 'Sacred Falls',
    damsire: 'Anabaa',
    owner: '許玉漢',
    prize: '0',
  );
}

void main() {
  test('horse sheet lines follow the Web formatters', () {
    final plain = _runner();
    expect(jockeyLine(plain), '何澤堯');
    expect(withDelta(plain.rating, fmtDelta(plain.rtgDelta)), '59');
    expect(formatCareer(plain.career), '30（2-5-1）');
    expect(horseWinText(plain), '12');
    expect(horsePlaceText(plain), '4.2');

    final allow = _runner(jockey: '周俊樂 (-2)');
    expect(jockeyLine(allow), '周俊樂（-2）');
    expect(hwDeltaOf(allow), '-2');

    final scratched = _runner(scratched: true, win: 37, place: 9);
    expect(horseWinText(scratched), '—');
    expect(horsePlaceText(scratched), '—');
  });

  test('race 1 horse 9 water anchor matches the Web demo', () {
    final horse = _runner(no: 9, win: 4, place: 1.6);
    final latest = waterHourSample(horse, 1, 0);
    final earlier = waterHourSample(horse, 1, 1);
    expect(wpWaterOf(horse, 1), 80);
    expect(latest.winW, 86);
    expect(latest.winF, 10);
    expect(latest.plaW, 84);
    expect(latest.plaF, 5);
    expect(latest.wpW, 81);
    expect(latest.wpF, 6);
    expect(waterTrendDir(latest.winW, earlier.winW), 'down');
    expect(waterHourLabels(18).first, '18:00');
    expect(waterHourSample(_runner(scratched: true), 6, 0).isEmpty, isTrue);
  });
}
