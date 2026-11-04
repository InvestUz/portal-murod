from importlib import import_module
from django.db import migrations, models


def preserve_sqlite_trigger(apps, schema_editor):
    # SQLite AddField/RemoveField may rebuild the table and drop its triggers.
    if schema_editor.connection.vendor == 'sqlite':
        prior = import_module('portal.migrations.0002_immutable_versions')
        prior.remove(apps, schema_editor)
        prior.install(apps, schema_editor)


class AddOcrQuality(migrations.AddField):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        super().database_forwards(app_label, schema_editor, from_state, to_state)
        preserve_sqlite_trigger(to_state.apps, schema_editor)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        super().database_backwards(app_label, schema_editor, from_state, to_state)
        preserve_sqlite_trigger(to_state.apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [('portal', '0004_fold_document_search')]
    operations = [AddOcrQuality(model_name='documentversion', name='ocr_quality',
                               field=models.JSONField(default=dict, blank=True))]
