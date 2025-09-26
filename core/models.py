from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django_q.tasks import async_task

from core.base_models import BaseModel
from core.choices import BlogPostStatus, ProfileStates
from core.model_utils import generate_random_key
from knowthyself.utils import get_knowthyself_logger

logger = get_knowthyself_logger(__name__)


class Profile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=30, unique=True, default=generate_random_key)
    experimental_flag = models.BooleanField(default=False)

    subscription = models.ForeignKey(
        "djstripe.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile",
        help_text="The user's Stripe Subscription object, if it exists",
    )
    product = models.ForeignKey(
        "djstripe.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile",
        help_text="The user's Stripe Product object, if it exists",
    )
    customer = models.ForeignKey(
        "djstripe.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile",
        help_text="The user's Stripe Customer object, if it exists",
    )

    state = models.CharField(
        max_length=255,
        choices=ProfileStates.choices,
        default=ProfileStates.STRANGER,
        help_text="The current state of the user's profile",
    )

    def track_state_change(self, to_state, metadata=None):
        async_task(
            "core.tasks.track_state_change",
            profile_id=self.id,
            from_state=self.current_state,
            to_state=to_state,
            metadata=metadata,
            source_function="Profile - track_state_change",
            group="Track State Change",
        )

    @property
    def current_state(self):
        if not self.state_transitions.all().exists():
            return ProfileStates.STRANGER
        latest_transition = self.state_transitions.latest("created_at")
        return latest_transition.to_state

    @property
    def has_active_subscription(self):
        return (
            self.current_state
            in [
                ProfileStates.SUBSCRIBED,
                ProfileStates.CANCELLED,
            ]
            or self.user.is_superuser
        )


class ProfileStateTransition(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="state_transitions",
    )
    from_state = models.CharField(max_length=255, choices=ProfileStates.choices)
    to_state = models.CharField(max_length=255, choices=ProfileStates.choices)
    backup_profile_id = models.IntegerField()
    metadata = models.JSONField(null=True, blank=True)


class BlogPost(BaseModel):
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    slug = models.SlugField(max_length=250)
    tags = models.TextField()
    content = models.TextField()
    icon = models.ImageField(upload_to="blog_post_icons/", blank=True)
    image = models.ImageField(upload_to="blog_post_images/", blank=True)
    status = models.CharField(
        max_length=10,
        choices=BlogPostStatus.choices,
        default=BlogPostStatus.DRAFT,
    )

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog_post", kwargs={"slug": self.slug})


class Feedback(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="feedback",
        help_text="The user who submitted the feedback",
    )
    feedback = models.TextField(
        help_text="The feedback text",
    )
    page = models.CharField(
        max_length=255,
        help_text="The page where the feedback was submitted",
    )

    def __str__(self):
        return f"{self.profile.user.email}: {self.feedback}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new:
            from django.conf import settings
            from django.core.mail import send_mail

            subject = "New Feedback Submitted"
            message = f"""
                New feedback was submitted:\n\n
                User: {self.profile.user.email if self.profile else "Anonymous"}
                Feedback: {self.feedback}
                Page: {self.page}
            """
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [settings.DEFAULT_FROM_EMAIL]

            send_mail(subject, message, from_email, recipient_list, fail_silently=True)


class Source(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sources",
    )
    personal_website = models.URLField(blank=True)
    hacker_news_username = models.CharField(blank=True, max_length=255)

    def __str__(self):
        return f"{self.profile.user.email}"


class HackerNewsStory(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="hacker_news_stories",
    )
    source = models.ForeignKey(
        Source,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="hacker_news_stories",
    )

    # Core story data
    story_id = models.BigIntegerField(unique=True)  # from "story_id" and "objectID"
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000, blank=True)
    author = models.CharField(max_length=100)

    # Metrics
    points = models.IntegerField(default=0)
    num_comments = models.IntegerField(default=0)

    # Timestamps
    post_created_at = models.DateTimeField()  # from "created_at"
    post_created_at_i = models.BigIntegerField()  # Unix timestamp from "created_at_i"
    post_updated_at = models.DateTimeField()  # from "updated_at"

    # Tags (optional - if you want to store the tags)
    tags = models.JSONField(default=list, blank=True)  # from "_tags"

    # Highlight results (optional - if you need search highlighting)
    highlight_result = models.JSONField(null=True, blank=True)  # from "_highlightResult"


class HackerNewsComment(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="hacker_news_comments",
    )
    source = models.ForeignKey(
        Source,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="hacker_news_comments",
    )
    # Core comment data
    comment_id = models.BigIntegerField(unique=True)  # from "objectID"
    comment_text = models.TextField()
    author = models.CharField(max_length=100)

    # Relationships
    story_id = models.BigIntegerField()  # from "story_id"
    story_title = models.CharField(max_length=500)  # from "story_title"
    parent_id = models.BigIntegerField(
        null=True, blank=True
    )  # from "parent_id" - for nested comments

    # Timestamps
    comment_created_at = models.DateTimeField()  # from "created_at"
    comment_created_at_i = models.BigIntegerField()  # Unix timestamp from "created_at_i"
    comment_updated_at = models.DateTimeField()  # from "updated_at"

    # Tags (optional)
    tags = models.JSONField(default=list, blank=True)  # from "_tags"

    # Highlight results (optional)
    highlight_result = models.JSONField(null=True, blank=True)  # from "_highlightResult"


class PersonalWebsitePage(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="personal_website_pages",
    )
    source = models.ForeignKey(
        Source,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="personal_website_pages",
    )

    content_type = models.CharField(max_length=20, blank=True)
    content = models.TextField(blank=True)
    word_count = models.IntegerField(default=0)

    meta_data = models.JSONField(default=dict, blank=True)

    links = models.JSONField(default=list, blank=True)
    images = models.JSONField(default=list, blank=True)

    published_date = models.DateTimeField(null=True, blank=True)
    last_modified = models.DateTimeField(null=True, blank=True)

    scraped_at = models.DateTimeField(auto_now_add=True)
