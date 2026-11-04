from django.db import migrations

FIELDS=['id','document_id','label','file_id','document_date','effective_date','change_note','created_by_id','created_at']

def install(apps,schema_editor):
    if schema_editor.connection.vendor=='postgresql':
        condition=' OR '.join(f'NEW.{field} IS DISTINCT FROM OLD.{field}' for field in FIELDS)
        schema_editor.execute(f"CREATE FUNCTION portal_immutable_version() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'Document version metadata is immutable' USING ERRCODE='23514'; END IF; RETURN NEW; END $$")
        schema_editor.execute('CREATE TRIGGER portal_immutable_version BEFORE UPDATE ON portal_documentversion FOR EACH ROW EXECUTE FUNCTION portal_immutable_version()')
    elif schema_editor.connection.vendor=='sqlite':
        condition=' OR '.join(f'NEW.{field} IS NOT OLD.{field}' for field in FIELDS)
        schema_editor.execute(f"CREATE TRIGGER portal_immutable_version BEFORE UPDATE ON portal_documentversion WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Document version metadata is immutable'); END")

def remove(apps,schema_editor):
    if schema_editor.connection.vendor=='postgresql':
        schema_editor.execute('DROP TRIGGER IF EXISTS portal_immutable_version ON portal_documentversion')
        schema_editor.execute('DROP FUNCTION IF EXISTS portal_immutable_version()')
    elif schema_editor.connection.vendor=='sqlite':
        schema_editor.execute('DROP TRIGGER IF EXISTS portal_immutable_version')

class Migration(migrations.Migration):
    dependencies=[('portal','0001_initial')]
    operations=[migrations.RunPython(install,remove)]
