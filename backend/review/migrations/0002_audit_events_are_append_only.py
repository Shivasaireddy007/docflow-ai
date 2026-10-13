from django.db import migrations

APPEND_ONLY = """
CREATE FUNCTION review_audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only (attempted %)', TG_OP;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER review_auditevent_append_only
    BEFORE UPDATE OR DELETE ON review_auditevent
    FOR EACH ROW EXECUTE FUNCTION review_audit_events_append_only();
"""

DROP = """
DROP TRIGGER review_auditevent_append_only ON review_auditevent;
DROP FUNCTION review_audit_events_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("review", "0001_initial")]

    operations = [migrations.RunSQL(APPEND_ONLY, DROP)]
