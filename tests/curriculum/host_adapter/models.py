from django.db import models


class Host(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    title = models.CharField(max_length=200, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    bio_html = models.TextField(blank=True, default="", editable=False)
    photo_url = models.URLField(max_length=500, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.bio:
            self.bio_html = f"<p>{self.bio}</p>"
        else:
            self.bio_html = ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "bio" in update_fields:
            kwargs["update_fields"] = {*update_fields, "bio_html"}
        super().save(*args, **kwargs)
