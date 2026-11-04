import io
import openpyxl
import pytest
from portal.file_processing import parse_import
from portal import models as m
from .test_content_and_files import approved_fixture

pytestmark=pytest.mark.django_db


@pytest.mark.parametrize('locale',['ru','uz','en'])
def test_template_is_filled_readable_xlsx_and_importable(hr,org,locale):
    user,_,api=hr
    response=api.get('/api/v1/employees/export',{'template':'true','locale':locale})
    assert response.status_code==200
    assert response['Content-Type']=='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert response['Content-Disposition'].endswith(f'employee-template-{locale}.xlsx"')
    book=openpyxl.load_workbook(io.BytesIO(response.content),read_only=False,data_only=False)
    try:
        assert len(book.worksheets)==2
        sheet=book.active
        assert sheet['A2'].value.startswith(('ПРИМЕР:','NAMUNA:','EXAMPLE:'))
        assert sheet['K2'].value is None
        assert sheet['A1'].value in {'ФИО','FIO','Full name'}
        assert sheet.column_dimensions['A'].width>30
        assert sheet['A1'].font.bold
        assert not any(cell.data_type=='f' for row in sheet for cell in row)
    finally:
        book.close()
    parsed=parse_import(response.content,'template.xlsx')
    assert len(parsed['rows'])==2
    assert parsed['rows'][0][7]=='1993-04-18'
    assert parsed['rows'][0][5]=='+998 90 123 45 67'
    parsed['rows']=parsed['rows'][:1]
    row=parsed['rows'][0]
    row[0]='Actual imported employee'
    row[2]=org[1].name
    row[3]=org[0].name
    file=approved_fixture(user,'template.xlsx',response.content,purpose='IMPORT')
    file.parsed_data=parsed
    file.save()
    preview=api.post('/api/v1/employees/import/preview',{'fileId':str(file.id)})
    assert preview.status_code==200
    value=preview.json()
    assert not value['errors'],value['errors']
    assert value['mapping']['birthday']==parsed['headers'][7]
    result=api.post(f'/api/v1/employees/import/{value["id"]}/commit',{'previewHash':value['previewHash'],'decisions':{}})
    assert result.status_code==200,result.content
    assert result.json()['created']==1
    assert m.Employee.objects.get(display_name='Actual imported employee').employee_number


@pytest.mark.parametrize('locale',['ru','uz','en'])
def test_unedited_examples_cannot_be_committed(hr,locale):
    user,_,api=hr
    response=api.get('/api/v1/employees/export',{'template':'true','locale':locale})
    file=approved_fixture(user,'template.xlsx',response.content,purpose='IMPORT')
    file.parsed_data=parse_import(response.content,'template.xlsx')
    file.save()
    preview=api.post('/api/v1/employees/import/preview',{'fileId':str(file.id)}).json()
    assert all(any(error['code']=='TEMPLATE_EXAMPLE_NOT_REPLACED' for error in row['errors']) for row in preview['rows'])
    before=m.Employee.objects.count()
    result=api.post(f'/api/v1/employees/import/{preview["id"]}/commit',{'previewHash':preview['previewHash'],'decisions':{}})
    assert result.status_code==409
    assert m.Employee.objects.count()==before


def test_template_is_management_only_and_locale_is_allowlisted(employee,hr):
    assert employee[2].get('/api/v1/employees/export',{'template':'true'}).status_code==403
    assert hr[2].get('/api/v1/employees/export',{'template':'true','locale':'../../private'}).status_code==400
