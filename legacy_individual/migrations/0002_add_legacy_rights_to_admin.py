from django.db import migrations

legacy_individual_rights = [
    200001, 200002, 200003, 200004,   # legacy individual: search / create / update / delete
    200011, 200012, 200013, 200014,   # legacy group: search / create / update / delete
    200021,                           # legacy import: execute
    200031,                           # legacy match review (phase 2)
    200041,                           # legacy promotion execute (phase 2)
]
imis_administrator_system = 64


def add_rights(apps, schema_editor):
    RoleRight = apps.get_model('core', 'RoleRight')
    Role = apps.get_model('core', 'Role')
    role = Role.objects.get(is_system=imis_administrator_system)
    for right_id in legacy_individual_rights:
        if not RoleRight.objects.filter(validity_to__isnull=True, role=role, right_id=right_id).exists():
            RoleRight.objects.create(role=role, right_id=right_id, audit_user_id=1)
    _clear_cache()


def remove_rights(apps, schema_editor):
    RoleRight = apps.get_model('core', 'RoleRight')
    RoleRight.objects.filter(
        role__is_system=imis_administrator_system,
        right_id__in=legacy_individual_rights,
        validity_to__isnull=True,
    ).delete()
    _clear_cache()


def _clear_cache():
    try:
        from django.core.cache import cache
        cache.clear()
    except Exception:  # pragma: no cover - cache backend may be unavailable
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('legacy_individual', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_rights, remove_rights),
    ]
