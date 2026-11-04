"""Bounded OCR with script-specific recognition and explicit quality metadata.

Secondary real recognition hypotheses aid search only. Never rewrite original files
or manufacture Uzbek spelling using a dictionary.
"""
import csv
import io
import os
import re
import subprocess
import time


class OcrFailure(Exception):
    pass


def parse_tsv(value):
    lines = {}
    for row in csv.DictReader(io.StringIO(value), delimiter='\t', quoting=csv.QUOTE_NONE):
        try:
            if int(row['level']) != 5 or not row.get('text', '').strip():
                continue
            confidence = float(row['conf'])
            box = tuple(int(row[k]) for k in ('left', 'top', 'width', 'height'))
            if not 0 <= confidence <= 100 or min(box) < 0:
                continue
            key = tuple(int(row[k]) for k in ('page_num', 'block_num', 'par_num', 'line_num'))
        except (KeyError, TypeError, ValueError):
            raise OcrFailure('OCR_INVALID_RESULT') from None
        lines.setdefault(key, []).append((row['text'].strip(), confidence, box))
        if len(lines) > 5000:
            raise OcrFailure('OCR_RESULT_LIMIT')
    result = []
    for words in lines.values():
        left = min(w[2][0] for w in words)
        top = min(w[2][1] for w in words)
        right = max(w[2][0]+w[2][2] for w in words)
        bottom = max(w[2][1]+w[2][3] for w in words)
        weight = sum(len(w[0]) for w in words)
        result.append({'text': ' '.join(w[0] for w in words),
                       'confidence': sum(len(w[0])*w[1] for w in words)/weight,
                       'box': (left, top, right-left, bottom-top)})
    return result


def overlap(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    area = max(0, min(x+w, xx+ww)-max(x, xx))*max(0, min(y+h, yy+hh)-max(y, yy))
    return area/max(1, min(w*h, ww*hh))


def recognize(image, languages, deadline):
    names = languages.split('+')
    if not names or any(not re.fullmatch(r'[A-Za-z_]+', name) for name in names):
        raise OcrFailure('OCR_LANGUAGES_UNAVAILABLE')
    profiles = [languages]
    if 'Latin' in names and 'uzb_cyrl' in names:
        profiles.extend(['Latin', 'uzb_cyrl'])
    variants = {}
    for profile in profiles:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise OcrFailure('OCR_TIMEOUT')
        try:
            value = subprocess.run(['tesseract', str(image), 'stdout', '-l', profile,
                                    '--psm', '3', '--oem', '1',
                                    '-c', 'tessedit_create_tsv=1', '-c', 'tessedit_create_txt=0'],
                                   capture_output=True, text=True, timeout=min(60, remaining),
                                   check=True, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
        except subprocess.TimeoutExpired:
            raise OcrFailure('OCR_TIMEOUT') from None
        except (OSError, subprocess.CalledProcessError):
            raise OcrFailure('OCR_FAILED') from None
        if len(value.stdout) > 8*1024*1024:
            raise OcrFailure('OCR_RESULT_LIMIT')
        variants[profile] = parse_tsv(value.stdout)
    baseline = variants[languages]
    if not baseline:
        raise OcrFailure('OCR_NO_TEXT')
    selected = []
    for line in baseline:
        letters = [c for c in line['text'] if c.isalpha()]
        cyrillic = sum('\u0400' <= c <= '\u052f' for c in letters)
        preferred = 'uzb_cyrl' if cyrillic > len(letters)/2 else 'Latin'
        choices = []
        for profile in ['Latin', 'uzb_cyrl']:
            matches = [(overlap(line['box'], other['box']), other)
                       for other in variants.get(profile, [])]
            matches = [(score, other) for score, other in matches if score >= .65]
            if matches:
                candidate = max(matches, key=lambda item: item[0])[1]
                letters = [c for c in candidate['text'] if c.isalpha()]
                cyrillic = sum('\u0400' <= c <= '\u052f' for c in letters)
                actual_script = 'uzb_cyrl' if cyrillic > len(letters)/2 else 'Latin'
                if letters and actual_script == profile:
                    choices.append((candidate['confidence'], profile == preferred, candidate))
        # A combined-language pass may render English in Cyrillic homoglyphs.
        # Compare independently recognized lines; script majority only breaks
        # confidence ties. No vocabulary or hard-coded word substitutions.
        candidate = max(choices, key=lambda item: item[:2])[2] if choices else line
        selected.append(candidate if candidate['confidence'] >= 35 else line)
    text = '\n'.join(line['text'] for line in selected)
    search = '\n'.join(dict.fromkeys(line['text'] for rows in variants.values() for line in rows))
    if max(len(text), len(search)) > 2_000_000:
        raise OcrFailure('TEXT_LIMIT')
    return {'text': text, 'searchText': search,
            'quality': {'meanConfidence': round(sum(v['confidence'] for v in selected)/len(selected), 2),
                        'lowConfidenceLines': sum(v['confidence'] < 65 for v in selected),
                        'lineCount': len(selected), 'profiles': profiles}}
