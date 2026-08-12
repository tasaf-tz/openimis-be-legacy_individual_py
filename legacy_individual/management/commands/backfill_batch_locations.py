"""Populate region/district on legacy import batches that predate those columns.

Scope is derived from the batch's own rows: each distinct individual location is walked up
to its district ancestor and the most common one wins. A batch covers one district, so a
split result means the data is not what we assume -- it is reported, not silently averaged.
"""
from collections import Counter

from django.core.management.base import BaseCommand

from legacy_individual.models import LegacyImportBatch, LegacyIndividual
from legacy_individual.services import LegacyApiImportService


def _district_of(location):
    node, hops = location, 0
    while node is not None and node.type != 'D' and hops < 5:
        node = node.parent
        hops += 1
    return node if (node is not None and node.type == 'D') else None


class Command(BaseCommand):
    help = 'Backfill region/district on legacy import batches from their imported rows.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--all', action='store_true',
                            help='Also recompute batches that already have a district.')
        parser.add_argument('--user', default=None,
                            help='Audit user for the write (default: first core user).')

    def handle(self, *args, **opts):
        from core.models import User
        from location.models import Location

        audit_user = (User.objects.filter(username=opts['user']).first()
                      if opts['user'] else User.objects.order_by('id').first())
        if audit_user is None and not opts['dry_run']:
            self.stderr.write(self.style.ERROR('no core user available for the audit trail'))
            return

        qs = LegacyImportBatch.objects.filter(is_deleted=False)
        if not opts['all']:
            qs = qs.filter(district__isnull=True)

        total = qs.count()
        if not total:
            self.stdout.write('nothing to backfill')
            return

        updated = skipped = split = 0
        for batch in qs:
            district, region = LegacyApiImportService.resolve_scope(batch.code)

            if district is None:
                loc_ids = (LegacyIndividual.objects
                           .filter(import_batch=batch, is_deleted=False, location__isnull=False)
                           .values_list('location_id', flat=True).distinct()[:500])
                districts = [d for d in
                             (_district_of(loc) for loc in
                              Location.objects.filter(id__in=list(loc_ids)).select_related(
                                  'parent', 'parent__parent'))
                             if d is not None]
                if not districts:
                    skipped += 1
                    self.stdout.write(f'  skip  {batch.code or batch.id}: no resolvable location')
                    continue
                counts = Counter(d.id for d in districts)
                if len(counts) > 1:
                    split += 1
                    self.stdout.write(self.style.WARNING(
                        f'  SPLIT {batch.code or batch.id}: rows span {len(counts)} districts '
                        f'-- using the most common'))
                district = next(d for d in districts if d.id == counts.most_common(1)[0][0])
                region = district.parent

            if opts['dry_run']:
                self.stdout.write(f'  would set {batch.code or batch.id} -> '
                                  f'{getattr(region, "name", None)} / {district.name}')
                continue

            batch.district = district
            batch.region = region
            batch.save(user=audit_user)
            updated += 1

        verb = 'would update' if opts['dry_run'] else 'updated'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {updated if not opts["dry_run"] else total - skipped} of {total} '
            f'(skipped {skipped}, split {split})'))
