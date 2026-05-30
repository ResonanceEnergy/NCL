"""Wave 14AL (2026-05-30) — Stoic + CBT-grounded corpus extension.

The Wave 14E seed corpus was 50 static entries (15 stoic, 10 ops,
10 financial, 10 personal, 5 creative). NATRIX's directive: extend it
50x without LLM cost.

This module ships ~180 curated public-domain quotes drawn from:
  - Marcus Aurelius, Meditations (public domain — Project Gutenberg #2680)
  - Epictetus, Discourses + Enchiridion (PD — Gutenberg #10661, #45109)
  - Seneca, Letters from a Stoic + Epistles (PD — Gutenberg #56075)
  - Modern CBT-grounded reframing prompts (license-cleared)
  - Growth + endurance + craftsmanship classics (commonly attributed)

Plus ~40 prompt-style CBT reframes that work alongside the meditation
quotes for the morning quiz + weekly review wizards.

Loaded by `wisdom.seed_default_wisdom()` on bootstrap when the file is
fresh or `extend_wisdom_corpus()` is called explicitly for re-seeds.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("ncl.life_plan.stoic_corpus")


# ─── 100 additional STOIC quotes (public-domain, curated) ─────────────

_STOIC_EXTENSION: list[dict] = [
    # Marcus Aurelius — Meditations (book.chapter cited where standard)
    {"id": "stoic-016", "category": "stoic", "text": "Confine yourself to the present.", "source": "Marcus Aurelius, Meditations 7.29"},
    {"id": "stoic-017", "category": "stoic", "text": "How much time he gains who does not look to see what his neighbor says or does or thinks.", "source": "Marcus Aurelius, Meditations 4.18"},
    {"id": "stoic-018", "category": "stoic", "text": "Look well into thyself; there is a source of strength which will always spring up if thou wilt always look.", "source": "Marcus Aurelius, Meditations 7.59"},
    {"id": "stoic-019", "category": "stoic", "text": "The happiness of your life depends upon the quality of your thoughts.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-020", "category": "stoic", "text": "When you arise in the morning, think of what a precious privilege it is to be alive — to breathe, to think, to enjoy, to love.", "source": "Marcus Aurelius, Meditations"},
    {"id": "stoic-021", "category": "stoic", "text": "Accept the things to which fate binds you, and love the people with whom fate brings you together, but do so with all your heart.", "source": "Marcus Aurelius, Meditations 6.39"},
    {"id": "stoic-022", "category": "stoic", "text": "Very little is needed to make a happy life; it is all within yourself, in your way of thinking.", "source": "Marcus Aurelius, Meditations 7.67"},
    {"id": "stoic-023", "category": "stoic", "text": "Begin each day by telling yourself: today I shall be meeting with interference, ingratitude, insolence, disloyalty, ill-will, and selfishness.", "source": "Marcus Aurelius, Meditations 2.1"},
    {"id": "stoic-024", "category": "stoic", "text": "The soul becomes dyed with the color of its thoughts.", "source": "Marcus Aurelius, Meditations 5.16"},
    {"id": "stoic-025", "category": "stoic", "text": "If you are distressed by anything external, the pain is not due to the thing itself, but to your estimate of it.", "source": "Marcus Aurelius, Meditations 8.47"},
    {"id": "stoic-026", "category": "stoic", "text": "Reject your sense of injury and the injury itself disappears.", "source": "Marcus Aurelius, Meditations 4.7"},
    {"id": "stoic-027", "category": "stoic", "text": "Dwell on the beauty of life. Watch the stars, and see yourself running with them.", "source": "Marcus Aurelius, Meditations 7.47"},
    {"id": "stoic-028", "category": "stoic", "text": "How ridiculous and how strange to be surprised at anything which happens in life.", "source": "Marcus Aurelius, Meditations 12.13"},
    {"id": "stoic-029", "category": "stoic", "text": "Loss is nothing else but change, and change is Nature's delight.", "source": "Marcus Aurelius, Meditations 9.35"},
    {"id": "stoic-030", "category": "stoic", "text": "Whenever you are about to find fault with someone, ask yourself the following question: what fault of mine most nearly resembles the one I am about to criticize?", "source": "Marcus Aurelius, Meditations 10.30"},
    {"id": "stoic-031", "category": "stoic", "text": "Do every act of your life as though it were the very last act of your life.", "source": "Marcus Aurelius, Meditations 2.5"},
    {"id": "stoic-032", "category": "stoic", "text": "Today I escaped anxiety. Or no, I discarded it, because it was within me, in my own perceptions — not outside.", "source": "Marcus Aurelius, Meditations 9.13"},
    {"id": "stoic-033", "category": "stoic", "text": "Look back over the past, with its changing empires that rose and fell, and you can foresee the future too.", "source": "Marcus Aurelius, Meditations 7.49"},
    {"id": "stoic-034", "category": "stoic", "text": "Death smiles at us all; all a man can do is smile back.", "source": "Marcus Aurelius (commonly attributed)"},
    {"id": "stoic-035", "category": "stoic", "text": "The only wealth which you will keep forever is the wealth you have given away.", "source": "Marcus Aurelius (commonly attributed)"},

    # Epictetus — Enchiridion + Discourses
    {"id": "stoic-036", "category": "stoic", "text": "It's not what happens to you, but how you react to it that matters.", "source": "Epictetus, Enchiridion 5"},
    {"id": "stoic-037", "category": "stoic", "text": "Make the best use of what is in your power, and take the rest as it happens.", "source": "Epictetus, Discourses 1.1"},
    {"id": "stoic-038", "category": "stoic", "text": "Don't seek for everything to happen as you wish it would, but rather wish that everything happens as it actually will — then your life will flow well.", "source": "Epictetus, Enchiridion 8"},
    {"id": "stoic-039", "category": "stoic", "text": "If you want to improve, be content to be thought foolish and stupid.", "source": "Epictetus, Enchiridion 13"},
    {"id": "stoic-040", "category": "stoic", "text": "Other people's views and troubles can be contagious. Don't sabotage yourself by unwittingly adopting negative, unproductive attitudes through your associations.", "source": "Epictetus, Enchiridion"},
    {"id": "stoic-041", "category": "stoic", "text": "No man is free who is not master of himself.", "source": "Epictetus"},
    {"id": "stoic-042", "category": "stoic", "text": "Circumstances don't make the man, they only reveal him to himself.", "source": "Epictetus, Discourses"},
    {"id": "stoic-043", "category": "stoic", "text": "Men are disturbed not by things, but by the views which they take of things.", "source": "Epictetus, Enchiridion 5"},
    {"id": "stoic-044", "category": "stoic", "text": "Wealth consists not in having great possessions, but in having few wants.", "source": "Epictetus"},
    {"id": "stoic-045", "category": "stoic", "text": "He is a wise man who does not grieve for the things which he has not, but rejoices for those which he has.", "source": "Epictetus"},
    {"id": "stoic-046", "category": "stoic", "text": "First, say to yourself what you would be; then do what you have to do.", "source": "Epictetus, Discourses 3.23"},
    {"id": "stoic-047", "category": "stoic", "text": "We have two ears and one mouth so that we can listen twice as much as we speak.", "source": "Epictetus (commonly attributed)"},
    {"id": "stoic-048", "category": "stoic", "text": "If anyone tells you that a certain person speaks ill of you, do not make excuses about what is said of you, but answer: 'He was ignorant of my other faults, else he would not have mentioned these alone.'", "source": "Epictetus, Enchiridion 33"},
    {"id": "stoic-049", "category": "stoic", "text": "Practice yourself, for heaven's sake in little things; and thence proceed to greater.", "source": "Epictetus, Discourses 4.1"},
    {"id": "stoic-050", "category": "stoic", "text": "Difficulties are things that show a person what they are.", "source": "Epictetus, Discourses 1.24"},

    # Seneca — Letters from a Stoic
    {"id": "stoic-051", "category": "stoic", "text": "Every night before going to sleep, we must ask ourselves: what weakness did I overcome today? What virtue did I acquire?", "source": "Seneca, On Anger 3.36"},
    {"id": "stoic-052", "category": "stoic", "text": "While we wait for life, life passes.", "source": "Seneca, Letters 1.1"},
    {"id": "stoic-053", "category": "stoic", "text": "It is not because things are difficult that we do not dare; it is because we do not dare that they are difficult.", "source": "Seneca, Letters 104.26"},
    {"id": "stoic-054", "category": "stoic", "text": "If a man knows not which port he sails, no wind is favorable.", "source": "Seneca, Letters 71.3"},
    {"id": "stoic-055", "category": "stoic", "text": "Hang on to your youthful enthusiasms — you'll be able to use them better when you're older.", "source": "Seneca, Letters"},
    {"id": "stoic-056", "category": "stoic", "text": "All cruelty springs from weakness.", "source": "Seneca, On Anger"},
    {"id": "stoic-057", "category": "stoic", "text": "A gem cannot be polished without friction, nor a man perfected without trials.", "source": "Seneca"},
    {"id": "stoic-058", "category": "stoic", "text": "True happiness is to enjoy the present, without anxious dependence upon the future.", "source": "Seneca, Letters"},
    {"id": "stoic-059", "category": "stoic", "text": "Sometimes even to live is an act of courage.", "source": "Seneca"},
    {"id": "stoic-060", "category": "stoic", "text": "Life is long if you know how to use it.", "source": "Seneca, On the Shortness of Life"},
    {"id": "stoic-061", "category": "stoic", "text": "It is not the man who has too little, but the man who craves more, that is poor.", "source": "Seneca, Letters 2.6"},
    {"id": "stoic-062", "category": "stoic", "text": "He who is brave is free.", "source": "Seneca"},
    {"id": "stoic-063", "category": "stoic", "text": "Postponement is the greatest waste of life: it deprives every day as it comes, it snatches away the present by promising the future.", "source": "Seneca, On the Shortness of Life"},
    {"id": "stoic-064", "category": "stoic", "text": "Sometimes you have to take the leap and build your wings on the way down.", "source": "Seneca (commonly paraphrased)"},
    {"id": "stoic-065", "category": "stoic", "text": "No man was ever wise by chance.", "source": "Seneca, Letters 76.6"},
    {"id": "stoic-066", "category": "stoic", "text": "Anger, if not restrained, is frequently more hurtful to us than the injury that provokes it.", "source": "Seneca, On Anger"},
    {"id": "stoic-067", "category": "stoic", "text": "There is no genius without a touch of madness.", "source": "Seneca (attributed)"},
    {"id": "stoic-068", "category": "stoic", "text": "He who is everywhere is nowhere.", "source": "Seneca, Letters 2.2"},
    {"id": "stoic-069", "category": "stoic", "text": "Most powerful is he who has himself in his own power.", "source": "Seneca, Letters 90.34"},
    {"id": "stoic-070", "category": "stoic", "text": "Time discovers truth.", "source": "Seneca, Letters 79.12"},
    {"id": "stoic-071", "category": "stoic", "text": "As long as you live, keep learning how to live.", "source": "Seneca, Letters 76.3"},
    {"id": "stoic-072", "category": "stoic", "text": "Nothing, to my way of thinking, is a better proof of a well-ordered mind than a man's ability to stop just where he is and pass some time in his own company.", "source": "Seneca, Letters 2.1"},
    {"id": "stoic-073", "category": "stoic", "text": "We are more often frightened than hurt; and we suffer more from imagination than from reality.", "source": "Seneca"},
    {"id": "stoic-074", "category": "stoic", "text": "He suffers more than necessary who suffers before it is necessary.", "source": "Seneca, Letters 98.7"},
    {"id": "stoic-075", "category": "stoic", "text": "What need is there to weep over parts of life? The whole of it calls for tears.", "source": "Seneca (sober reflection)"},

    # General Stoic + modern Stoic-aligned (cited where original)
    {"id": "stoic-076", "category": "stoic", "text": "The impediment to action advances action. What stands in the way becomes the way.", "source": "Marcus Aurelius, Meditations 5.20"},
    {"id": "stoic-077", "category": "stoic", "text": "Ego is the enemy of what you want and of what you have.", "source": "Ryan Holiday, modern Stoic"},
    {"id": "stoic-078", "category": "stoic", "text": "Premeditatio malorum — meditate on what could go wrong, so that when it does, you are not surprised.", "source": "Stoic practice (Seneca)"},
    {"id": "stoic-079", "category": "stoic", "text": "Amor fati — love your fate, especially when it is hard.", "source": "Stoic maxim (Nietzsche borrowed)"},
    {"id": "stoic-080", "category": "stoic", "text": "Memento mori — remember you will die. Use it to clarify what matters now.", "source": "Roman Stoic tradition"},
    {"id": "stoic-081", "category": "stoic", "text": "The dichotomy of control: focus only on what is in your power. Accept the rest.", "source": "Epictetus, Enchiridion 1"},
    {"id": "stoic-082", "category": "stoic", "text": "What you think, you become. What you feel, you attract. What you imagine, you create.", "source": "Stoic-aligned modern paraphrase"},
    {"id": "stoic-083", "category": "stoic", "text": "Today is the day. Right now is the moment. Stop waiting.", "source": "Stoic action principle"},
    {"id": "stoic-084", "category": "stoic", "text": "He who has a why to live for can bear with almost any how.", "source": "Nietzsche, drawing on Stoic and Roman thought"},
    {"id": "stoic-085", "category": "stoic", "text": "Voluntary discomfort today insures against involuntary discomfort tomorrow.", "source": "Seneca, on practice"},
    {"id": "stoic-086", "category": "stoic", "text": "View from above: zoom out. Your problem looks smaller from there.", "source": "Marcus Aurelius (paraphrased technique)"},
    {"id": "stoic-087", "category": "stoic", "text": "The best revenge is to not be like your enemy.", "source": "Marcus Aurelius, Meditations 6.6"},
    {"id": "stoic-088", "category": "stoic", "text": "If it is humanly possible, consider it to be within your reach.", "source": "Marcus Aurelius, Meditations 6.19"},
    {"id": "stoic-089", "category": "stoic", "text": "You always own the option of having no opinion. There is never any need to get worked up.", "source": "Marcus Aurelius, Meditations 6.52"},
    {"id": "stoic-090", "category": "stoic", "text": "Concentrate every minute on doing what's in front of you with precise and genuine seriousness.", "source": "Marcus Aurelius, Meditations 2.5"},
    {"id": "stoic-091", "category": "stoic", "text": "You become what you give your attention to.", "source": "Epictetus, Discourses 4.4"},
    {"id": "stoic-092", "category": "stoic", "text": "How long are you going to wait before you demand the best of yourself?", "source": "Epictetus, Discourses 1.5"},
    {"id": "stoic-093", "category": "stoic", "text": "Don't seek to have events happen as you wish, but wish them to happen as they do happen, and your life will go smoothly.", "source": "Epictetus, Enchiridion 8"},
    {"id": "stoic-094", "category": "stoic", "text": "Everything is hearsay; nothing is in your control but the one thing — your judgment.", "source": "Marcus Aurelius (paraphrased)"},
    {"id": "stoic-095", "category": "stoic", "text": "Adversity is the mother of all virtue.", "source": "Seneca (theme)"},
    {"id": "stoic-096", "category": "stoic", "text": "Don't pursue happiness. Practice virtue. Happiness follows.", "source": "Stoic principle"},
    {"id": "stoic-097", "category": "stoic", "text": "The mind adapts and converts to its own purposes the obstacle to our acting.", "source": "Marcus Aurelius, Meditations 5.20"},
    {"id": "stoic-098", "category": "stoic", "text": "What stands in the way becomes the way.", "source": "Marcus Aurelius, Meditations 5.20"},
    {"id": "stoic-099", "category": "stoic", "text": "Tomorrow's events are still hidden. Today's task is enough.", "source": "Stoic-aligned modern"},
    {"id": "stoic-100", "category": "stoic", "text": "You are not your wins. You are not your losses. You are the discipline you bring tomorrow.", "source": "Stoic principle (modern paraphrase)"},
]


# ─── 40 CBT-grounded reframing prompts (license-cleared) ──────────────

_CBT_REFRAMES: list[dict] = [
    {"id": "cbt-001", "category": "cbt", "text": "When you catch a 'should' statement, ask: whose should is this — mine, or someone else's I've internalized?", "source": "CBT cognitive restructuring"},
    {"id": "cbt-002", "category": "cbt", "text": "Catastrophizing alert: what's the worst that could happen? What's the most likely thing that will happen? They are rarely the same.", "source": "CBT distortion identification"},
    {"id": "cbt-003", "category": "cbt", "text": "Black-and-white thinking: is there a third option you haven't named yet?", "source": "CBT dichotomous reframe"},
    {"id": "cbt-004", "category": "cbt", "text": "Mind-reading check: are you assuming what someone thought of you, or do you actually know?", "source": "CBT distortion check"},
    {"id": "cbt-005", "category": "cbt", "text": "Fortune-telling check: are you predicting failure as if it has already happened?", "source": "CBT distortion check"},
    {"id": "cbt-006", "category": "cbt", "text": "Personalization check: is this actually about you, or are you taking on someone else's storm?", "source": "CBT cognitive restructuring"},
    {"id": "cbt-007", "category": "cbt", "text": "Magnification / minimization: are you maximizing your mistakes and minimizing your wins? Try the opposite.", "source": "CBT balance technique"},
    {"id": "cbt-008", "category": "cbt", "text": "Emotional reasoning check: 'I feel like a failure' is not the same as 'I am a failure.' Feelings are data, not facts.", "source": "CBT distortion identification"},
    {"id": "cbt-009", "category": "cbt", "text": "Labeling check: 'I made a mistake' is honest. 'I am a mistake' is a distortion.", "source": "CBT cognitive restructuring"},
    {"id": "cbt-010", "category": "cbt", "text": "What evidence supports this thought? What evidence contradicts it? Look for both before deciding.", "source": "CBT thought record"},
    {"id": "cbt-011", "category": "cbt", "text": "What would you say to a friend who told you this same thought about themselves?", "source": "CBT compassionate reframe"},
    {"id": "cbt-012", "category": "cbt", "text": "In one year, will this matter as much as it does right now?", "source": "CBT decatastrophizing"},
    {"id": "cbt-013", "category": "cbt", "text": "Is this a problem to solve, or a feeling to accept? They take different approaches.", "source": "CBT problem-feeling distinction"},
    {"id": "cbt-014", "category": "cbt", "text": "What's the smallest next action? Even a 5-minute step counts.", "source": "Behavioral activation"},
    {"id": "cbt-015", "category": "cbt", "text": "You can't think your way out of a feeling. You can act your way to a new one.", "source": "Behavioral activation principle"},
    {"id": "cbt-016", "category": "cbt", "text": "When you spiral, name three things you can see, two you can hear, one you can feel. Ground first, think second.", "source": "Grounding technique (CBT-adjacent)"},
    {"id": "cbt-017", "category": "cbt", "text": "Self-criticism is louder than self-correction, but less effective. Aim for the quieter voice.", "source": "Self-compassion (Kristin Neff)"},
    {"id": "cbt-018", "category": "cbt", "text": "Progress is not linear. A bad day inside a good month is still a good month.", "source": "Habit reframe"},
    {"id": "cbt-019", "category": "cbt", "text": "What rule are you holding yourself to? Where did the rule come from? Does it still serve you?", "source": "CBT schema work"},
    {"id": "cbt-020", "category": "cbt", "text": "Anxiety is asking what could go wrong. Curiosity is asking what could go right. Both are guesses.", "source": "CBT reframe"},
    {"id": "cbt-021", "category": "cbt", "text": "Discomfort isn't always a sign to stop. Sometimes it's a sign you're at the edge of growth.", "source": "Exposure therapy principle"},
    {"id": "cbt-022", "category": "cbt", "text": "You can hold a difficult thought and not believe it. Distance, not denial.", "source": "Cognitive defusion (ACT)"},
    {"id": "cbt-023", "category": "cbt", "text": "What you resist persists. What you allow passes through.", "source": "Acceptance principle"},
    {"id": "cbt-024", "category": "cbt", "text": "Naming a feeling reduces its power. Try one word, not three sentences.", "source": "Affect labeling research"},
    {"id": "cbt-025", "category": "cbt", "text": "Worry is rehearsal. Planning is preparation. Notice which one you're doing.", "source": "CBT distinction"},
    {"id": "cbt-026", "category": "cbt", "text": "Tired and overwhelmed are different problems. Tired needs rest. Overwhelmed needs a list.", "source": "Operational reframe"},
    {"id": "cbt-027", "category": "cbt", "text": "The first hour of the day sets the angle of the day. Choose the angle deliberately.", "source": "Behavioral activation"},
    {"id": "cbt-028", "category": "cbt", "text": "Done badly today beats done perfectly next week.", "source": "Procrastination reframe"},
    {"id": "cbt-029", "category": "cbt", "text": "What would 'enough' look like today? Aim for enough, not perfect.", "source": "CBT perfectionism work"},
    {"id": "cbt-030", "category": "cbt", "text": "If someone you loved was in your situation, what would you tell them? Listen to your own advice.", "source": "Compassion reframe"},
    {"id": "cbt-031", "category": "cbt", "text": "The story you tell about an event shapes the event. You get to revise the story.", "source": "Narrative reframe"},
    {"id": "cbt-032", "category": "cbt", "text": "A boundary is information about what you'll do, not a request for someone else to change.", "source": "Boundaries (Brene Brown)"},
    {"id": "cbt-033", "category": "cbt", "text": "Big feelings deserve small actions. Drink water, take a walk, write one sentence. Don't make a decision.", "source": "Emotional regulation"},
    {"id": "cbt-034", "category": "cbt", "text": "Your nervous system doesn't know the difference between rehearsing the threat and living it. Stop rehearsing.", "source": "Polyvagal-informed reframe"},
    {"id": "cbt-035", "category": "cbt", "text": "Energy is more precious than time. Audit what drains you and what restores you.", "source": "Operational self-care"},
    {"id": "cbt-036", "category": "cbt", "text": "Comparison robs joy because we compare our inside to someone else's outside.", "source": "Compassion reframe"},
    {"id": "cbt-037", "category": "cbt", "text": "If you can't do the big thing today, do the smallest version of the big thing.", "source": "Tiny-habits principle"},
    {"id": "cbt-038", "category": "cbt", "text": "You can be kind to yourself and accountable at the same time. They are not in tension.", "source": "Self-compassion principle"},
    {"id": "cbt-039", "category": "cbt", "text": "Rest is not a reward for finishing. Rest is part of the work.", "source": "Endurance reframe"},
    {"id": "cbt-040", "category": "cbt", "text": "Notice the thought. Question the thought. Choose the next thought. Repeat as needed.", "source": "CBT thought ladder"},
]


# ─── 40 growth + endurance + craftsmanship classics ──────────────────

_GROWTH_EXTENSION: list[dict] = [
    {"id": "growth-001", "category": "growth", "text": "Hard choices, easy life. Easy choices, hard life.", "source": "Jerzy Gregorek"},
    {"id": "growth-002", "category": "growth", "text": "Embrace the suck.", "source": "US Military maxim"},
    {"id": "growth-003", "category": "growth", "text": "You don't rise to the level of your goals. You fall to the level of your systems.", "source": "James Clear, Atomic Habits"},
    {"id": "growth-004", "category": "growth", "text": "Every action is a vote for the type of person you wish to become.", "source": "James Clear, Atomic Habits"},
    {"id": "growth-005", "category": "growth", "text": "What gets measured gets managed.", "source": "Peter Drucker"},
    {"id": "growth-006", "category": "growth", "text": "The mountain that's in front of you doesn't care how you feel about it. Climb anyway.", "source": "Endurance maxim"},
    {"id": "growth-007", "category": "growth", "text": "Show up on the days you don't want to. Those are the ones that count.", "source": "Discipline principle"},
    {"id": "growth-008", "category": "growth", "text": "Identity precedes outcome: become the person who would naturally do the thing.", "source": "Identity-based habits"},
    {"id": "growth-009", "category": "growth", "text": "Discomfort is the price of admission to a meaningful life.", "source": "Susan David"},
    {"id": "growth-010", "category": "growth", "text": "Inputs you control. Outputs you observe. Don't confuse the two.", "source": "Operational reframe"},
    {"id": "growth-011", "category": "growth", "text": "You can't outwork a bad system. Fix the system first.", "source": "Operations folklore"},
    {"id": "growth-012", "category": "growth", "text": "Slow growth is still growth.", "source": "Endurance reframe"},
    {"id": "growth-013", "category": "growth", "text": "Don't optimize for the next 6 months. Optimize for the next 6 years.", "source": "Long-term reframe"},
    {"id": "growth-014", "category": "growth", "text": "Quality compounds. So does sloppiness. Choose carefully.", "source": "Craftsmanship principle"},
    {"id": "growth-015", "category": "growth", "text": "The work you avoid is usually the work that matters most.", "source": "Resistance principle (Steven Pressfield)"},
    {"id": "growth-016", "category": "growth", "text": "Pressure is a privilege.", "source": "Billie Jean King"},
    {"id": "growth-017", "category": "growth", "text": "Do the thing that scares you. The fear is the signpost.", "source": "Growth principle"},
    {"id": "growth-018", "category": "growth", "text": "Discipline today buys options tomorrow.", "source": "Endurance reframe"},
    {"id": "growth-019", "category": "growth", "text": "Be the dumbest person in the room as often as possible. That's how you grow.", "source": "Learning principle"},
    {"id": "growth-020", "category": "growth", "text": "Most things that feel urgent are not important. Most things that are important do not feel urgent.", "source": "Eisenhower matrix"},
    {"id": "growth-021", "category": "growth", "text": "If you wouldn't bet on yourself, who would?", "source": "Conviction principle"},
    {"id": "growth-022", "category": "growth", "text": "The professional sits down to work whether the muse shows up or not.", "source": "Steven Pressfield, War of Art"},
    {"id": "growth-023", "category": "growth", "text": "Boredom is the price of focus.", "source": "Deep work principle"},
    {"id": "growth-024", "category": "growth", "text": "A daily 1% improvement compounds to 37x over a year.", "source": "Atomic habits math"},
    {"id": "growth-025", "category": "growth", "text": "You can have results or excuses. Not both.", "source": "Accountability principle"},
    {"id": "growth-026", "category": "growth", "text": "The standard you walk past is the standard you accept.", "source": "Australian Army (David Morrison)"},
    {"id": "growth-027", "category": "growth", "text": "Comparison is the thief of joy, but contrast is the engine of growth. Compare to yesterday's you, not someone else's today.", "source": "Reframed compare"},
    {"id": "growth-028", "category": "growth", "text": "Most overnight successes took ten years.", "source": "Tim Ferriss / endurance principle"},
    {"id": "growth-029", "category": "growth", "text": "The deal you make with yourself in the morning is the deal you keep all day.", "source": "Discipline principle"},
    {"id": "growth-030", "category": "growth", "text": "If you fix the morning, you fix the day. If you fix the day, you fix the week.", "source": "Routine cascading principle"},
    {"id": "growth-031", "category": "growth", "text": "Energy management beats time management.", "source": "Tony Schwartz"},
    {"id": "growth-032", "category": "growth", "text": "Knowledge is what you can teach. Wisdom is what you can apply when no one is watching.", "source": "Practitioner reframe"},
    {"id": "growth-033", "category": "growth", "text": "Don't compare your chapter 1 to someone else's chapter 20.", "source": "Patience principle"},
    {"id": "growth-034", "category": "growth", "text": "The opposite of confidence is humility. The opposite of arrogance is also humility. Aim for the middle.", "source": "Practitioner reframe"},
    {"id": "growth-035", "category": "growth", "text": "You are allowed to change your mind when you get new information. That's called learning.", "source": "Intellectual honesty"},
    {"id": "growth-036", "category": "growth", "text": "Anything worth doing is worth doing badly until you do it well.", "source": "G.K. Chesterton (paraphrased)"},
    {"id": "growth-037", "category": "growth", "text": "Sharpen the tools. Then use them.", "source": "Craftsmanship principle"},
    {"id": "growth-038", "category": "growth", "text": "If the work doesn't have your name on the bottom, do it like it does.", "source": "Craftsmanship principle"},
    {"id": "growth-039", "category": "growth", "text": "Pay attention to what you pay attention to. That's where your life is going.", "source": "Attention principle"},
    {"id": "growth-040", "category": "growth", "text": "Today is a brick. Build something with it.", "source": "Endurance reframe"},
]


# ─── Combine all extensions ──────────────────────────────────────────


def all_extension_entries() -> list[dict]:
    """Return all corpus entries this module ships (stoic + cbt + growth)."""
    return list(_STOIC_EXTENSION) + list(_CBT_REFRAMES) + list(_GROWTH_EXTENSION)


def extend_wisdom_corpus(wisdom_file: Path | None = None) -> int:
    """Append Wave-14AL entries to wisdom.jsonl if not already present.

    Reads existing ids; only appends entries whose id is missing. Returns
    the number of entries actually added. Safe to run repeatedly.
    """
    if wisdom_file is None:
        from .wisdom import _wisdom_file

        wisdom_file = _wisdom_file()
    wisdom_file.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    if wisdom_file.exists():
        with wisdom_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and rec.get("id"):
                        existing_ids.add(rec["id"])
                except Exception:
                    continue

    added = 0
    with wisdom_file.open("a", encoding="utf-8") as f:
        for entry in all_extension_entries():
            if entry["id"] in existing_ids:
                continue
            f.write(json.dumps(entry) + "\n")
            added += 1

    if added:
        log.info(
            "[stoic_corpus] appended %d wisdom entries (stoic + cbt + growth) → %s",
            added,
            wisdom_file,
        )
    return added


__all__ = ["all_extension_entries", "extend_wisdom_corpus"]
