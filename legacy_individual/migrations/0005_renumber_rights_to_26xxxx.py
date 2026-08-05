"""Move the legacy_individual rights off 2000xx (owned upstream by payment_cycle) onto 2600xx."""
from django.db import migrations
from django.utils import timezone

# legacy_individual is the only claimant -> close old, open new
EXCLUSIVE = {
    200011: 260011,
    200012: 260012,
    200013: 260013,
    200014: 260014,
    200021: 260021,
    200031: 260031,
    200041: 260041,
}

# shared with payment_cycle -> add the new code, leave the old row open
SHARED = {
    200001: 260001,
    200002: 260002,
    200003: 260003,
    200004: 260004,
}


def _open(RoleRight, role_id, right_id):
    return RoleRight.objects.filter(
        role_id=role_id, right_id=right_id, validity_to__isnull=True)


def _grant(RoleRight, role_id, right_id):
    if not _open(RoleRight, role_id, right_id).exists():
        RoleRight.objects.create(role_id=role_id, right_id=right_id, audit_user_id=-1)


def renumber(apps, schema_editor):
    RoleRight = apps.get_model('core', 'RoleRight')
    now = timezone.now()

    for old, new in EXCLUSIVE.items():
        rows = RoleRight.objects.filter(right_id=old, validity_to__isnull=True)
        for role_id in list(rows.values_list('role_id', flat=True)):
            _grant(RoleRight, role_id, new)
        rows.update(validity_to=now)

    legacy_roles = set(
        RoleRight.objects
        .filter(right_id__in=list(EXCLUSIVE.values()), validity_to__isnull=True)
        .values_list('role_id', flat=True))

    for old, new in SHARED.items():
        for role_id in legacy_roles:
            if _open(RoleRight, role_id, old).exists():
                _grant(RoleRight, role_id, new)

    _clear_cache()


def restore(apps, schema_editor):
    RoleRight = apps.get_model('core', 'RoleRight')

    RoleRight.objects.filter(
        right_id__in=list(EXCLUSIVE.values()) + list(SHARED.values()),
        validity_to__isnull=True,
    ).delete()

    for old in EXCLUSIVE:
        RoleRight.objects.filter(right_id=old, validity_to__isnull=False).update(validity_to=None)

    _clear_cache()


def _clear_cache():
    try:
        from django.core.cache import cache
        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern('rights_*')
        else:
            cache.clear()
    except Exception:  # pragma: no cover - cache backend may be unavailable
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('legacy_individual', '0004_alter_historicallegacyindividual_first_name_and_more'),
    ]

    operations = [
        migrations.RunPython(renumber, restore),
    ]
