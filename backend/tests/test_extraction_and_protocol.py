"""Real PDF/DOCX extraction. ClamAV response cases below are simulated protocol tests."""
import io
import shutil
import zipfile
from datetime import datetime,timedelta,timezone

import pytest
from PIL import Image,ImageDraw,ImageFont
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject

from portal.file_processing import ProcessingError,clamav_scan,extract_text,validate_zip

HEADER='Embedded searchable header with more than forty characters in the document'


def text_page(image=None):
    writer=PdfWriter()
    if image is None:
        page=writer.add_blank_page(width=900,height=600)
        original=b''
    else:
        data=io.BytesIO();image.save(data,format='PDF',resolution=150)
        reader=PdfReader(io.BytesIO(data.getvalue()))
        page=writer.add_page(reader.pages[0]);original=page.get_contents().get_data()
    resources=page['/Resources']
    resources[NameObject('/Font')]=DictionaryObject({NameObject('/FTest'):DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})})
    stream=DecodedStreamObject()
    stream.set_data(original+f'\nBT /FTest 12 Tf 20 {float(page.mediabox.height)-20} Td ({HEADER}) Tj ET\n'.encode())
    page[NameObject('/Contents')]=writer._add_object(stream)
    result=io.BytesIO();writer.write(result)
    return result.getvalue()


def test_text_pdf_does_not_require_ocr_tools(monkeypatch):
    def unnecessary(*args,**kwargs):
        raise AssertionError('Text-only PDF must not invoke OCR')
    monkeypatch.setattr('portal.file_processing.subprocess.run',unnecessary)
    result=extract_text(text_page(),'text.pdf','eng',80)
    assert HEADER in result['text'] and result['pages']==1


@pytest.mark.skipif(not shutil.which('tesseract') or not shutil.which('pdftoppm'),reason='Real OCR binaries are not installed')
def test_mixed_pdf_indexes_scan_below_long_searchable_header(monkeypatch):
    # Use the system eng model; this regression does not certify Uzbek OCR quality.
    monkeypatch.delenv('TESSDATA_PREFIX',raising=False)
    image=Image.new('RGB',(1800,1200),'white')
    font=ImageFont.truetype('DejaVuSans.ttf',64)
    draw=ImageDraw.Draw(image)
    draw.text((100,200),'UNIQUE SCANNED CONTRACT',font=font,fill='black')
    draw.text((100,320),'COMPANY POLICY NUMBER 150',font=font,fill='black')
    data=text_page(image)
    # Ensure this is genuinely a mixed page: only the header exists in its text layer.
    embedded=PdfReader(io.BytesIO(data)).pages[0].extract_text()
    assert len(embedded)>40 and 'SCANNED CONTRACT' not in embedded
    monkeypatch.setenv('OCR_LANGUAGES','eng')
    from worker import execute
    result=execute({'kind':'EXTRACT','fileName':'mixed.pdf','purpose':'DOCUMENT'},data)
    assert HEADER in result['text']
    assert 'UNIQUE SCANNED CONTRACT' in result['text']
    assert 'COMPANY POLICY NUMBER 150' in result['text']


def test_worker_reports_missing_antivirus_without_approving_file(monkeypatch):
    monkeypatch.setenv('CLAMAV_HOST','')
    from worker import execute
    result=execute({'kind':'SCAN','fileName':'synthetic.csv','purpose':'IMPORT'},b'name,position\nsynthetic,specialist\n')
    assert result=={'error':'ANTIVIRUS_UNAVAILABLE'}


def test_docx_paragraphs_and_tables_preserve_unicode():
    from docx import Document
    document=Document();document.add_paragraph('Текст: Ў Қ Ғ Ҳ; Ö Ğ Ş Ç; O‘ G‘ sh ch; English.')
    table=document.add_table(rows=1,cols=2);table.cell(0,0).text='Номер';table.cell(0,1).text='150'
    data=io.BytesIO();document.save(data)
    result=extract_text(data.getvalue(),'mixed.docx','eng',80)
    assert 'Ў Қ Ғ Ҳ; Ö Ğ Ş Ç; O‘ G‘ sh ch' in result['text']
    assert 'Номер | 150' in result['text'] and result['pages'] is None


def test_duplicate_archive_paths_are_rejected():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('word/document.xml','first')
        archive.writestr('word/./document.xml','ambiguous second')
    with pytest.raises(ProcessingError,match='DUPLICATE_ARCHIVE_ENTRY'):
        validate_zip(data.getvalue())


class ProtocolSocket:
    """A deterministic protocol stub, not a ClamAV engine or malware test."""
    def __init__(self,response):
        self.response=response;self.sent=[]
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def sendall(self,data):self.sent.append(data)
    def recv(self,size):
        result=self.response[:size];self.response=self.response[size:];return result


@pytest.mark.parametrize('age,result,expected',[
    (timedelta(hours=1),'stream: OK',None),
    (timedelta(days=4),'stream: OK','ANTIVIRUS_SIGNATURES_STALE'),
    (-timedelta(days=2),'stream: OK','ANTIVIRUS_SIGNATURES_INVALID'),
    (timedelta(hours=1),'stream: Synthetic-Test FOUND','MALWARE_DETECTED'),
    (timedelta(hours=1),'stream: size limit exceeded ERROR','ANTIVIRUS_INCOMPLETE'),
])
def test_clamav_protocol_fails_closed(monkeypatch,age,result,expected):
    stamp=(datetime.now(timezone.utc)-age).strftime('%a %b %d %H:%M:%S %Y')
    sockets=[ProtocolSocket(f'ClamAV simulated/12345/{stamp}\0'.encode()),ProtocolSocket((result+'\0').encode())]
    iterator=iter(sockets)
    monkeypatch.setattr('portal.file_processing.socket.create_connection',lambda *args,**kwargs:next(iterator))
    if expected:
        with pytest.raises(ProcessingError,match=expected):clamav_scan(b'synthetic safe bytes','test-scanner')
    else:
        assert clamav_scan(b'synthetic safe bytes','test-scanner')['signatureVersion']=='12345'
        assert b'zINSTREAM\0' in sockets[1].sent and sockets[1].sent[-1]==b'\0\0\0\0'

def test_xlsx_without_dimension_cannot_bypass_import_row_limit():
    import re
    import openpyxl
    from portal.file_processing import parse_import
    workbook=openpyxl.Workbook();sheet=workbook.active
    sheet.append(['name','position'])
    for index in range(2001):sheet.append([f'person {index}','specialist'])
    raw=io.BytesIO();workbook.save(raw)
    stripped=io.BytesIO()
    with zipfile.ZipFile(raw) as source,zipfile.ZipFile(stripped,'w',zipfile.ZIP_DEFLATED) as destination:
        for info in source.infolist():
            data=source.read(info.filename)
            if info.filename=='xl/worksheets/sheet1.xml':
                data=re.sub(rb'<dimension\b[^>]*/>',b'',data)
            destination.writestr(info.filename,data)
    with pytest.raises(ProcessingError,match='IMPORT_ROW_LIMIT'):
        parse_import(stripped.getvalue(),'no-dimension.xlsx')

@pytest.mark.parametrize('content',[
    '<w:p><w:fldSimple w:instr="DDEAUTO dangerous-command"/></w:p>',
    '<w:p><w:r><w:instrText>DDE</w:instrText></w:r><w:r><w:instrText>AUTO unsafe</w:instrText></w:r></w:p>',
    '<w:p><w:r><w:instrText>INCLUDETEXT unsafe</w:instrText></w:r></w:p>',
])
def test_word_active_field_instructions_are_rejected(content):
    from portal.file_processing import inspect_office
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'+content+'</w:document>')
    with pytest.raises(ProcessingError,match='ACTIVE_OFFICE_CONTENT'):inspect_office(data.getvalue())


def test_word_external_template_is_rejected_but_normal_https_link_is_allowed():
    from portal.file_processing import inspect_office
    def package(kind,target):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('word/_rels/settings.xml.rels',f'<Relationships><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" TargetMode="External" Target="{target}"/></Relationships>')
        return data.getvalue()
    with pytest.raises(ProcessingError,match='ACTIVE_OFFICE_CONTENT'):inspect_office(package('attachedTemplate','https://example.invalid/template.dotm'))
    with pytest.raises(ProcessingError,match='ACTIVE_OFFICE_CONTENT'):inspect_office(package('hyperlink','file:///network-share/file'))
    inspect_office(package('hyperlink','https://example.invalid/document'))


def test_normal_docx_passes_structural_inspection_without_claiming_av_result():
    from docx import Document
    from portal.file_processing import inspect_clean_file
    doc=Document();doc.add_paragraph('Ordinary safe document content')
    data=io.BytesIO();doc.save(data)
    result=inspect_clean_file(data.getvalue(),'document.docx','DOCUMENT',80)
    assert result['mimeType'].endswith('wordprocessingml.document')
    assert 'status' not in result and 'scannerVersion' not in result

def test_ole_payload_in_root_embedding_folder_is_rejected():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:archive.writestr('embeddings/payload.bin',b'not executable test fixture')
    with pytest.raises(ProcessingError,match='ACTIVE_CONTENT'):validate_zip(data.getvalue())


@pytest.mark.parametrize('url',['file:///network-share/document','javascript:alert(1)','data:text/html,unsafe'])
def test_pdf_external_file_or_script_uri_is_rejected(url):
    from portal.file_processing import pdf_reader
    from pypdf.generic import ArrayObject,TextStringObject,NumberObject
    writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
    link=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),NameObject('/Rect'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(100),NumberObject(100)]),NameObject('/A'):DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject(url)})})
    page[NameObject('/Annots')]=ArrayObject([writer._add_object(link)])
    data=io.BytesIO();writer.write(data)
    with pytest.raises(ProcessingError,match='ACTIVE_CONTENT'):pdf_reader(data.getvalue(),80)


def test_ocr_rejects_blank_scans_instead_of_silent_ready(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from portal.ocr import recognize, OcrFailure
    monkeypatch.setattr('portal.ocr.subprocess.run', lambda *args, **kwargs: SimpleNamespace(stdout='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'))
    import time
    with pytest.raises(OcrFailure, match='OCR_NO_TEXT'):
        recognize(tmp_path/'blank.png', 'eng', time.monotonic()+10)


@pytest.mark.parametrize('value', [
    {'meanConfidence': float('nan')}, {'meanConfidence': float('inf')},
    {'meanConfidence': True}, {'ocrPages': True}, {'unknown': 'data'}, {'profiles': [123]},
])
def test_worker_quality_metadata_rejects_non_finite_or_untyped_values(value):
    from portal.file_views import valid_ocr_quality
    assert not valid_ocr_quality(value)
