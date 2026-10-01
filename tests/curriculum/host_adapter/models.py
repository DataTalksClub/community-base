from django.db import models


class Host(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    kind = models.CharField(max_length=20)
    bio = models.TextField(blank=True, default="")
    bio_html = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
