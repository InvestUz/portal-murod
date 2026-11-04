"""Synthetic raster PDF regression benchmark of the real isolated extraction worker.

This starts at EXTRACT, after AV approval. It does not certify the AV/upload chain
or real company scans. Thresholds are engineering targets, not owner acceptance.
"""
import argparse
import io
import json
import math
import os
import platform
import statistics
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
CASES = {
    'uz-current': ("O‘ZBEKISTON RESPUBLIKASI\nG‘ALABA VA SHAHAR\nCHORAK HISOBOTI 150", ['g‘alaba', 'chorak']),
    'uz-reformed': ('ÖZBEKÇA HUJJAT\nĞALABA VA ŞAHAR\nÇORAK HISOBOTI', ['Ğalaba', 'şahar', 'çorak']),
    'uz-cyrillic': ('ЎЗБЕКЧА ҲУЖЖАТ\nҚЎШИМЧА ҒАЛАБА\nХОДИМЛАР БЎЛИМИ', ['қўшимча', 'ғалаба', 'ходимлар']),
    'ru': ('ПРИКАЗ КОМПАНИИ\nУПРАВЛЕНИЕ ДОКУМЕНТАМИ\nНОМЕР 150', ['приказ', 'документами']),
    'en': ('COMPANY POLICY\nEMPLOYEE INFORMATION\nDOCUMENT NUMBER 150', ['employee', 'document']),
    'mixed': ('ЎЗБЕКЧА ҲУЖЖАТ\nÖZBEKÇA HUJJAT\nПРИКАЗ КОМПАНИИ\nCOMPANY POLICY 150', ['ҳужжат', 'özbekça', 'приказ', 'policy']),
}


def normalize(value):
    for character in '‘’ʻʼ`':
        value = value.replace(character, "'")
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def distance(a, b):
    row = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1]+1, row[j]+1, row[j-1]+(x != y)))
        row = next_row
    return row[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()
    os.environ['TESSDATA_PREFIX'] = str(Path(args.models).resolve())
    os.environ['OCR_LANGUAGES'] = 'Latin+uzb_cyrl+rus+eng+tur'
    from PIL import Image, ImageDraw, ImageFont
    from portal.domain import search_fold
    from worker import execute
    rows = []
    for name, (expected, queries) in CASES.items():
        for font_name in ['DejaVuSans', 'DejaVuSerif']:
            for degradation in ['clean', 'jpeg-tilt']:
                image = Image.new('RGB', (1800, 1200), 'white')
                draw = ImageDraw.Draw(image)
                font = ImageFont.truetype(font_name+'.ttf', 52)
                draw.multiline_text((100, 180), expected, font=font, fill='black', spacing=38)
                if degradation == 'jpeg-tilt':
                    raw = io.BytesIO()
                    image.save(raw, format='JPEG', quality=65)
                    image = Image.open(io.BytesIO(raw.getvalue())).rotate(1, fillcolor='white')
                pdf = io.BytesIO()
                image.save(pdf, format='PDF', resolution=150)
                started = time.monotonic()
                result = execute({'kind': 'EXTRACT', 'fileName': 'synthetic.pdf', 'purpose': 'DOCUMENT'}, pdf.getvalue())
                elapsed = time.monotonic()-started
                observed = result.get('text', '')
                index = search_fold(observed+'\n'+result.get('searchText', ''))
                hits = sum(search_fold(query) in index for query in queries)
                actual, reference = normalize(observed), normalize(expected)
                row = {'case': name, 'font': font_name, 'degradation': degradation,
                       'error': result.get('error'), 'expected': expected, 'observed': observed,
                       'characterEdits': distance(reference, actual), 'referenceCharacters': len(reference),
                       'wordEdits': distance(reference.split(), actual.split()), 'referenceWords': len(reference.split()),
                       'queryHits': hits, 'queryCount': len(queries), 'seconds': round(elapsed, 3),
                       'quality': result.get('quality', {})}
                rows.append(row)
                print(json.dumps({k: row[k] for k in ['case', 'font', 'degradation', 'error', 'characterEdits', 'queryHits', 'seconds']}), flush=True)
    times = sorted(row['seconds'] for row in rows)
    summary = {'cases': len(rows), 'errors': sum(bool(row['error']) for row in rows),
               'weightedCharacterErrorRate': sum(r['characterEdits'] for r in rows)/sum(r['referenceCharacters'] for r in rows),
               'weightedWordErrorRate': sum(r['wordEdits'] for r in rows)/sum(r['referenceWords'] for r in rows),
               'queryRecall': sum(r['queryHits'] for r in rows)/sum(r['queryCount'] for r in rows),
               'medianSeconds': statistics.median(times), 'p95Seconds': times[math.ceil(len(times)*.95)-1], 'maxSeconds': max(times)}
    passed = summary['errors'] == 0 and summary['weightedCharacterErrorRate'] <= .02 and summary['queryRecall'] >= .95
    groups = {}
    for key in CASES:
        subset = [row for row in rows if row['case'] == key]
        groups[key] = {'characterErrorRate': sum(row['characterEdits'] for row in subset)/sum(row['referenceCharacters'] for row in subset),
                       'queryRecall': sum(row['queryHits'] for row in subset)/sum(row['queryCount'] for row in subset)}
    report = {'percentileMethod': 'nearest-rank', 'summaryByScript': groups, 'generatedAt': datetime.now(timezone.utc).isoformat(), 'scope': __doc__,
              'platform': platform.platform(), 'python': platform.python_version(),
              'engineeringTargets': {'characterErrorRateMax': .02, 'queryRecallMin': .95},
              'passed': passed, 'summary': summary, 'results': rows}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary), flush=True)
    if args.strict and not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
