from django.db import migrations

GRANTS = ((260051, 260001), (260061, 260011))  # (new right, granted where this right is held)


def grant(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for right, held in GRANTS:
            cursor.execute(
                """
                INSERT INTO "tblRoleRight" ("RoleID", "RightID", "ValidityFrom", "AuditUserId")
                SELECT DISTINCT rr."RoleID", %s, NOW(), 1
                FROM "tblRoleRight" rr JOIN "tblRole" r ON r."RoleID" = rr."RoleID"
                WHERE rr."RightID" = %s AND rr."ValidityTo" IS NULL AND r."ValidityTo" IS NULL
                  AND NOT EXISTS (SELECT 1 FROM "tblRoleRight" x
                                  WHERE x."RoleID" = rr."RoleID" AND x."RightID" = %s AND x."ValidityTo" IS NULL)
                """,
                [right, held, right],
            )


def revoke(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DELETE FROM "tblRoleRight" WHERE "RightID" IN %s', [tuple(r for r, _ in GRANTS)])


class Migration(migrations.Migration):

    dependencies = [
        ('legacy_individual', '0011_rm4_search_indexes'),
    ]

    operations = [migrations.RunPython(grant, revoke)]
