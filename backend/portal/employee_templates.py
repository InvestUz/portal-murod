"""Filled, localized HR templates; static XLSX assets, no runtime Node dependency."""
import csv
import io
from pathlib import Path
from django.http import HttpResponse
from .errors import PortalError


def template_response(locale,format='xlsx'):
    if locale not in {'ru','uz','en'}:
        raise PortalError('INVALID_LOCALE')
    if format not in {'xlsx','csv'}:
        raise PortalError('INVALID_FORMAT')
    path=Path(__file__).resolve().parent/'assets'/f'employee-template-{locale}.xlsx'
    if format=='xlsx':
        response=HttpResponse(path.read_bytes(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        import openpyxl
        book=openpyxl.load_workbook(path,read_only=True,data_only=True,keep_links=False)
        try:
            output=io.StringIO()
            writer=csv.writer(output)
            for row in book.active.iter_rows(values_only=True):
                if any(value is not None for value in row):
                    writer.writerow([value.date().isoformat() if hasattr(value,'date') else value if value is not None else '' for value in row])
        finally:
            book.close()
        response=HttpResponse('\ufeff'+output.getvalue(),content_type='text/csv; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="employee-template-{locale}.{format}"'
    return response
