from django.contrib import admin
from django.db import transaction

from community_base.voting.models import Poll, PollOption, PollVote
from community_base.voting.services import emit_poll_opened


class PollOptionInline(admin.TabularInline):
    model = PollOption
    extra = 3
    fields = ("title", "description", "proposed_by")
    readonly_fields = ("proposed_by",)


@admin.action(description="Close selected polls")
def close_polls(_modeladmin, _request, queryset):
    queryset.update(status="closed")


@admin.action(description="Reopen selected polls")
def reopen_polls(_modeladmin, request, queryset):
    polls = tuple(queryset)
    queryset.update(status="open")
    for poll in polls:
        poll.status = "open"
        transaction.on_commit(lambda item=poll: emit_poll_opened(item, actor=request.user))


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "poll_type",
        "status",
        "required_level",
        "allow_proposals",
        "max_votes_per_user",
        "closes_at",
        "created_at",
    )
    list_filter = ("status", "poll_type")
    search_fields = ("title", "description")
    actions = (close_polls, reopen_polls)
    inlines = (PollOptionInline,)
    readonly_fields = ("required_level",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and obj.status == "open":
            transaction.on_commit(lambda: emit_poll_opened(obj, actor=request.user))


@admin.register(PollOption)
class PollOptionAdmin(admin.ModelAdmin):
    list_display = ("title", "poll", "proposed_by", "created_at")
    list_filter = ("poll",)
    search_fields = ("title", "description")


@admin.register(PollVote)
class PollVoteAdmin(admin.ModelAdmin):
    list_display = ("user", "poll", "option", "created_at")
    list_filter = ("poll",)
    search_fields = ("user__email",)
