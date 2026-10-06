"""The questions we ask Jev about every forum post.

Jev answers each question with a typed value:
  Choice -> one label from a fixed set (plus probabilities and confidence)
  Noul   -> probability (0 to 1) that a yes/no statement is true
  Score  -> position on an ordered scale (can be fractional, e.g. 2.4)
"""

from typesafe_sdk import Choice, Noul, Score

QUESTIONS = {
    # CHOICE: exactly one label wins. Keys are the labels you get back.
    "post_type": Choice(
        instructions="What kind of post is this?",
        criteria={
            "help_request": "The author asks for help or advice with a problem",
            "discussion": "An opinion or open-ended conversation starter",
            "showcase": "The author shares their own project or achievement",
            "promotion": "Advertising a product, service, link or referral",
            "off_topic": "Unrelated to the community's topic",
        },
    ),
    # NOUL: one yes/no proposition. The optional criteria define what
    # "true" and "false" mean, which makes the question less ambiguous.
    "is_spam": Noul(
        instructions="Is this post spam?",
        criteria={
            "true": "Unsolicited promotion, repeated links, scams or gibberish",
            "false": "A genuine post by a real community member",
        },
    ),
    "shares_personal_info": Noul(
        instructions="Does the post reveal private personal information such as "
        "a phone number, home address, or email address?",
    ),
    # SCORE: criteria is an ORDERED list, lowest level first.
    # Level 0 is the first item, level 4 is the last.
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
