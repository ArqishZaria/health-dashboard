from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0002_alter_uploadbatch_form_type'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='budgetallocation',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='budgetallocation',
            constraint=models.UniqueConstraint(
                fields=['portfolio', 'region', 'fiscal_year'],
                name='uniq_budget_regional',
            ),
        ),
        migrations.AddConstraint(
            model_name='budgetallocation',
            constraint=models.UniqueConstraint(
                fields=['portfolio', 'fiscal_year'],
                condition=models.Q(region__isnull=True),
                name='uniq_budget_national',
            ),
        ),
    ]