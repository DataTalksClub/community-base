import pytest

from community_base.accounts.models import User
from community_base.accounts.services.privacy import build_user_data_export
from community_base.voting.models import Poll, PollOption, PollVote

pytestmark = pytest.mark.django_db


def test_privacy_export_contains_only_members_votes_and_proposals():
    member = User.objects.create_user(email="member@example.com")
    other = User.objects.create_user(email="other@example.com")
    poll = Poll.objects.create(title="Next topic")
    member_option = PollOption.objects.create(
        poll=poll, title="Member proposal", proposed_by=member
    )
    other_option = PollOption.objects.create(poll=poll, title="Other", proposed_by=other)
    PollVote.objects.create(poll=poll, option=other_option, user=member)
    PollVote.objects.create(poll=poll, option=member_option, user=other)

    export = build_user_data_export(member)

    assert [row["option_id"] for row in export["poll_votes"]] == [str(other_option.pk)]
    assert [row["title"] for row in export["poll_proposals"]] == ["Member proposal"]
