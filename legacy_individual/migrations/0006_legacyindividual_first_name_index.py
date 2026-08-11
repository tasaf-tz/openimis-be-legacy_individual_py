# last_name was indexed but first_name was not, so ordering the individuals page
# by first name fell back to a sort of the whole table.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('legacy_individual', '0005_renumber_rights_to_26xxxx'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='legacyindividual',
            index=models.Index(
                fields=['first_name'],
                name='legacy_ind_first_n_idx',
            ),
        ),
    ]
