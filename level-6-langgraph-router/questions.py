"""Level 6 questions (copied from Level 5, which copied them from Level 4).

Same idea as Level 1, with two fixes learned from the Level 1 output:
  1. The community topic is now stated, so Jev can judge "off_topic"
     (in Level 1, a cricket post was never marked off-topic because Jev
     was never told what the community is about).
  2. "Self promotion" and "spam" are now separate questions (in Level 1,
     one honest app link produced is_spam = 0.52, a coin flip).
"""

from typesafe_sdk import Choice, Noul, Score

COMMUNITY_TOPIC = "Python programming and software development"

QUESTIONS = {
    "post_type": Choice(
        instructions=f"This is a forum about {COMMUNITY_TOPIC}. "
        "What kind of post is this?",
        criteria={
            "help_request": "The author asks for help or advice with a problem",
            "discussion": "An on-topic opinion or conversation starter",
            "showcase": "The author shares their own project or achievement",
            "promotion": "Advertising a product, service, link or referral",
            "off_topic": f"Unrelated to {COMMUNITY_TOPIC}",
        },
    ),
    "is_spam": Noul(
        instructions="Is this post spam?",
        criteria={
            "true": "Bulk or deceptive promotion: referral codes, scam offers, "
            "repeated links, shouting, or gibberish",
            "false": "A genuine post by a real member, including one honest "
            "mention of their own project",
        },
    ),
    "is_self_promotion": Noul(
        instructions="Is the author promoting their own product, service or link?",
    ),
    # Level 4 change: judged on CONTEXT, not on the email domain. A contact-like
    # string inside a code sample or config is not private information, but a
    # phone number or email offered in the open is. (Keyed on context because
    # real and fake data can both use example.com.)
    "shares_personal_info": Noul(
        instructions="Does the post reveal a real person's private personal information?",
        criteria={
            "true": "Real private contact or location details about a person, such "
            "as a phone number, home address or personal email shared in the open",
            "false": "No private details, or contact-like text that is clearly part "
            "of a code sample, configuration, documentation or test data",
        },
    ),
    "toxicity": Score(
        instructions="How hostile or abusive is the tone of this post?",
        criteria=[
            "Friendly or neutral",
            "Slightly sharp or sarcastic",
            "Rude or dismissive",
            "Insulting or aggressive",
            "Hateful, threatening or harassing",
        ],
    ),
}
