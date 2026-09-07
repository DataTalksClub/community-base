from django import forms

from community_base.curriculum.models import Cohort, Course, Module, Unit


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = (
            "title",
            "slug",
            "description",
            "cover_image_url",
            "required_level",
            "default_unit_required_level",
            "status",
            "discussion_url",
            "github_repo_url",
            "docs_url",
            "faq_url",
            "hashtag",
            "visible",
            "tags",
            "testimonials",
        )


class CohortForm(forms.ModelForm):
    class Meta:
        model = Cohort
        fields = (
            "title",
            "slug",
            "mode",
            "start_date",
            "end_date",
            "registration_url",
            "curriculum_format",
            "hashtag",
            "finished",
            "visible",
            "max_participants",
        )


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = (
            "title",
            "slug",
            "sort_order",
            "overview",
        )


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = (
            "title",
            "slug",
            "sort_order",
            "video_url",
            "body",
            "homework",
            "timestamps",
            "is_preview",
            "required_level",
            "available_after_days",
        )
