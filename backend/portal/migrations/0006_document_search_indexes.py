from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


def ensure_extension(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        # portalctl/init creates this using the DB administrator, not portal_app.
        # A privileged test database can also install the trusted extension here.
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')


class PostgresAddIndex(migrations.AddIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'postgresql':
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'postgresql':
            super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [('portal', '0005_ocr_quality')]
    operations = [
        migrations.RunPython(ensure_extension, migrations.RunPython.noop),
        PostgresAddIndex(model_name='document', index=GinIndex(fields=['normalized_title'], name='portal_doc_title_trgm', opclasses=['gin_trgm_ops'])),
        PostgresAddIndex(model_name='documentversion', index=GinIndex(fields=['normalized_text'], name='portal_doc_text_trgm', opclasses=['gin_trgm_ops'])),
    ]
