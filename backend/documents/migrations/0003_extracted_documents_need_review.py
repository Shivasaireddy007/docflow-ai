from django.db import migrations


def forwards(apps, schema_editor):
    # "extracted" no longer exists: decisions now follow every extraction. Documents extracted
    # before rules existed have no decision, so a person should look at them.
    apps.get_model("documents", "Document").objects.filter(status="extracted").update(status="needs_review")


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_review_statuses_and_claims")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
