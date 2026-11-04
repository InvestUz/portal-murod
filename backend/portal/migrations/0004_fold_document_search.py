import re
import unicodedata
from django.db import migrations


def reindex(apps,schema_editor):
    Version=apps.get_model('portal','DocumentVersion')
    translation=str.maketrans({'ö':'o','ğ':'g','ş':'s','ç':'c','ў':'у','қ':'к','ғ':'г','ҳ':'х'})
    for version in Version.objects.only('pk','extracted_text').iterator(chunk_size=100):
        value=unicodedata.normalize('NFKC',version.extracted_text).lower()
        value=re.sub('[‘’ʻʼ`´]',"'",value)
        value=' '.join(value.replace("o'",'ö').replace("g'",'ğ').replace('sh','ş').replace('ch','ç').split()).translate(translation)
        Version.objects.filter(pk=version.pk).update(normalized_text=value)


class Migration(migrations.Migration):
    dependencies=[('portal','0003_workerheartbeat')]
    operations=[migrations.RunPython(reindex,migrations.RunPython.noop)]
